import os
import sys
import json
import re
import logging
from typing import Dict, Any, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

# Ensure backend root is on sys.path if run directly
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    from app.config import settings
    DB_HOST = settings.effective_host
    DB_PORT = settings.DB_PORT
    DB_USER = settings.DB_USER
    DB_PASSWORD = settings.DB_PASSWORD
    DB_NAME = settings.DB_NAME
    RAW_SYNC_URL = settings.sync_database_url
except Exception:
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    if DB_HOST.lower() == "localhost":
        DB_HOST = "127.0.0.1"
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "Admin@123")
    DB_NAME = os.getenv("DB_NAME", "finalairajmaster")
    RAW_SYNC_URL = os.getenv("DATABASE_URL", "")

# Configure logger to output only to stderr so stdout remains clean for JSON-RPC
logger = logging.getLogger("mcp.postgres")
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def get_db_connection():
    """Returns a psycopg2 connection for both local PostgreSQL and live cloud DATABASE_URL."""
    env_db_url = os.getenv("DATABASE_URL") or (
        RAW_SYNC_URL if (os.getenv("VERCEL") or os.getenv("SPACE_ID") or os.getenv("ENV_MODE") == "huggingface") else ""
    )
    if env_db_url:
        dsn = env_db_url.strip()
        if dsn.startswith("postgresql+psycopg2://"):
            dsn = "postgresql://" + dsn[len("postgresql+psycopg2://"):]
        elif dsn.startswith("postgres://"):
            dsn = "postgresql://" + dsn[len("postgres://"):]
        return psycopg2.connect(dsn, cursor_factory=RealDictCursor)

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
        cursor_factory=RealDictCursor
    )


def _clean_breadcrumbs(items: List[Optional[str]]) -> List[str]:
    """Filters out None and blank entries from breadcrumb sequences."""
    return [str(x).strip() for x in items if x is not None and str(x).strip()]


# =====================================================================
# Database Tools Implementation
# =====================================================================

def tool_list_tables() -> Dict[str, Any]:
    """Lists all user tables in finalairajmaster with columns and row count."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name;
            """)
            tables = [row["table_name"] for row in cur.fetchall()]
            
            table_info = []
            for t in tables:
                cur.execute(f"SELECT count(*) AS cnt FROM {t};")
                cnt = cur.fetchone()["cnt"]
                
                cur.execute("""
                    SELECT count(*) AS col_cnt 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public' AND table_name = %s;
                """, (t,))
                col_cnt = cur.fetchone()["col_cnt"]
                
                table_info.append({
                    "table_name": t,
                    "row_count": cnt,
                    "column_count": col_cnt
                })
                
            return {
                "database": DB_NAME,
                "total_tables": len(tables),
                "tables": table_info
            }


def tool_describe_table(table_name: str) -> Dict[str, Any]:
    """Describes table columns, data types, constraints, and nullable flags."""
    # Sanitize table_name against alphanumeric and underscore
    if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    column_name, 
                    data_type, 
                    character_maximum_length, 
                    is_nullable, 
                    column_default
                FROM information_schema.columns 
                WHERE table_schema = 'public' AND table_name = %s 
                ORDER BY ordinal_position;
            """, (table_name,))
            columns = cur.fetchall()
            
            if not columns:
                raise ValueError(f"Table '{table_name}' does not exist in schema 'public'.")
                
            # Get primary keys
            cur.execute("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_name = %s;
            """, (table_name,))
            pk_rows = cur.fetchall()
            primary_keys = [r["column_name"] for r in pk_rows]

            return {
                "table_name": table_name,
                "primary_keys": primary_keys,
                "columns": [
                    {
                        "column_name": col["column_name"],
                        "data_type": col["data_type"],
                        "is_nullable": col["is_nullable"],
                        "default": col["column_default"],
                        "is_primary_key": col["column_name"] in primary_keys
                    }
                    for col in columns
                ]
            }


def tool_read_query(query: str, limit: int = 100) -> Dict[str, Any]:
    """
    Executes a safe read-only SQL SELECT / WITH / EXPLAIN query.
    Prevents any DDL/DML statements (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE).
    """
    cleaned = query.strip()
    norm = cleaned.lower()
    
    # Safety verification
    allowed_starts = ("select", "with", "explain", "show")
    if not any(norm.startswith(prefix) for prefix in allowed_starts):
        raise ValueError("Only read-only queries (SELECT, WITH, EXPLAIN, SHOW) are permitted.")
        
    forbidden = ["insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "create ", "grant ", "revoke ", "exec ", "execute "]
    for word in forbidden:
        if word in norm:
            raise ValueError(f"Prohibited mutation clause detected: '{word.strip()}'")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Enforce read-only transaction mode
            cur.execute("SET TRANSACTION READ ONLY;")
            cur.execute(cleaned)
            rows = cur.fetchall()
            
            if len(rows) > limit:
                truncated_rows = rows[:limit]
                truncated = True
            else:
                truncated_rows = rows
                truncated = False

            return {
                "query": cleaned,
                "row_count": len(rows),
                "returned_count": len(truncated_rows),
                "truncated": truncated,
                "rows": truncated_rows
            }


def tool_get_administrative_lineage(entity_name_or_pincode: str) -> Dict[str, Any]:
    """
    Reconstructs the full 6-tier Rajasthan administrative lineage from PostgreSQL tables:
    State -> Division -> District -> Sub-Division -> Tehsil/Block -> Gram Panchayat / ULB -> Village/Ward.
    """
    term = entity_name_or_pincode.strip()
    sterm = f"%{term}%"
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # 1. Pincode Check
            if re.match(r"^\d{6}$", term):
                cur.execute("""
                    SELECT p.*, d.name_en AS district_name, div.name_en AS division_name,
                           tb.name_en AS tehsil_name, ulb.name_en AS ulb_name, gp.name_en AS gp_name
                    FROM pincodes p
                    LEFT JOIN districts d ON p.district_id = d.id
                    LEFT JOIN divisions div ON d.division_id = div.id
                    LEFT JOIN tehsils_blocks tb ON p.tehsil_block_id = tb.id
                    LEFT JOIN urban_local_bodies ulb ON p.ulb_id = ulb.id
                    LEFT JOIN gram_panchayats gp ON p.gram_panchayat_id = gp.id
                    WHERE p.pincode = %s LIMIT 1;
                """, (term,))
                row = cur.fetchone()
                if row:
                    return {
                        "matched": True,
                        "entity_type": "Pincode",
                        "entity_name": f"Pincode {row['pincode']} ({row['city_or_village']})",
                        "lineage": {
                            "state": "Rajasthan",
                            "division": row["division_name"],
                            "district": row["district_name"],
                            "tehsil_or_block": row["tehsil_name"],
                            "urban_local_body": row["ulb_name"],
                            "gram_panchayat": row["gp_name"],
                            "locality": row["city_or_village"],
                            "pincode": row["pincode"]
                        },
                        "breadcrumbs": _clean_breadcrumbs([
                            "Rajasthan",
                            row["division_name"],
                            row["district_name"],
                            row["tehsil_name"],
                            row["ulb_name"] or row["gp_name"],
                            row["city_or_village"]
                        ])
                    }

            # 2. Exact District Match (prevents e.g. 'Balotra' from resolving to a block before its district)
            cur.execute("""
                SELECT d.*, div.name_en AS division_name, div.divisional_commissioner
                FROM districts d
                LEFT JOIN divisions div ON d.division_id = div.id
                WHERE LOWER(d.name_en) = LOWER(%s) OR LOWER(COALESCE(d.name_hi, '')) = LOWER(%s) LIMIT 1;
            """, (term, term))
            exact_d_row = cur.fetchone()
            if exact_d_row:
                return {
                    "matched": True,
                    "entity_type": "District",
                    "entity_name": exact_d_row["name_en"],
                    "lineage": {
                        "state": "Rajasthan",
                        "division": exact_d_row["division_name"],
                        "district": exact_d_row["name_en"],
                        "zila_pramukh": exact_d_row["zila_pramukh"],
                        "collectorate": exact_d_row["collectorate_details"],
                        "divisional_commissioner": exact_d_row["divisional_commissioner"],
                        "lgd_code": exact_d_row["lgd_code"]
                    },
                    "breadcrumbs": _clean_breadcrumbs(["Rajasthan", exact_d_row["division_name"], exact_d_row["name_en"]])
                }

            # 3. Village Match
            cur.execute("""
                SELECT v.*, d.name_en AS district_name, div.name_en AS division_name,
                       tb.name_en AS tehsil_name, gp.name_en AS gp_name, gp.sarpanch
                FROM villages v
                LEFT JOIN districts d ON v.district_id = d.id
                LEFT JOIN divisions div ON d.division_id = div.id
                LEFT JOIN tehsils_blocks tb ON v.tehsil_block_id = tb.id
                LEFT JOIN gram_panchayats gp ON v.gram_panchayat_id = gp.id
                WHERE v.name_en ILIKE %s OR v.name_hi ILIKE %s LIMIT 1;
            """, (sterm, sterm))
            v_row = cur.fetchone()
            if v_row:
                return {
                    "matched": True,
                    "entity_type": "Village",
                    "entity_name": v_row["name_en"],
                    "lineage": {
                        "state": "Rajasthan",
                        "division": v_row["division_name"],
                        "district": v_row["district_name"],
                        "tehsil": v_row["tehsil_name"],
                        "gram_panchayat": v_row["gp_name"],
                        "revenue_village": v_row["name_en"],
                        "patwar_circle": v_row["patwar_circle"],
                        "patwari": v_row["patwari"],
                        "sarpanch": v_row["sarpanch"],
                        "pincode": v_row["pincode"],
                        "lgd_code": v_row["lgd_code"]
                    },
                    "breadcrumbs": _clean_breadcrumbs([
                        "Rajasthan",
                        v_row["division_name"],
                        v_row["district_name"],
                        v_row["tehsil_name"],
                        v_row["gp_name"],
                        v_row["name_en"]
                    ])
                }

            # 4. Tehsil / Block Match
            cur.execute("""
                SELECT tb.*, d.name_en AS district_name, div.name_en AS division_name, sd.name_en AS sub_division_name
                FROM tehsils_blocks tb
                LEFT JOIN districts d ON tb.district_id = d.id
                LEFT JOIN divisions div ON d.division_id = div.id
                LEFT JOIN sub_divisions sd ON tb.sub_division_id = sd.id
                WHERE tb.name_en ILIKE %s OR tb.name_hi ILIKE %s LIMIT 1;
            """, (sterm, sterm))
            tb_row = cur.fetchone()
            if tb_row:
                return {
                    "matched": True,
                    "entity_type": tb_row["entity_type"] or "Tehsil/Block",
                    "entity_name": tb_row["name_en"],
                    "lineage": {
                        "state": "Rajasthan",
                        "division": tb_row["division_name"],
                        "district": tb_row["district_name"],
                        "sub_division": tb_row["sub_division_name"],
                        "tehsil_or_block": tb_row["name_en"],
                        "tehsildar": tb_row["tehsildar_details"],
                        "bdo": tb_row["bdo_details"],
                        "lgd_code": tb_row["lgd_code"]
                    },
                    "breadcrumbs": _clean_breadcrumbs([
                        "Rajasthan",
                        tb_row["division_name"],
                        tb_row["district_name"],
                        tb_row["sub_division_name"],
                        tb_row["name_en"]
                    ])
                }

            # 5. Fuzzy District Match
            cur.execute("""
                SELECT d.*, div.name_en AS division_name, div.divisional_commissioner
                FROM districts d
                LEFT JOIN divisions div ON d.division_id = div.id
                WHERE d.name_en ILIKE %s OR d.name_hi ILIKE %s LIMIT 1;
            """, (sterm, sterm))
            d_row = cur.fetchone()
            if d_row:
                return {
                    "matched": True,
                    "entity_type": "District",
                    "entity_name": d_row["name_en"],
                    "lineage": {
                        "state": "Rajasthan",
                        "division": d_row["division_name"],
                        "district": d_row["name_en"],
                        "zila_pramukh": d_row["zila_pramukh"],
                        "collectorate": d_row["collectorate_details"],
                        "divisional_commissioner": d_row["divisional_commissioner"],
                        "lgd_code": d_row["lgd_code"]
                    },
                    "breadcrumbs": _clean_breadcrumbs(["Rajasthan", d_row["division_name"], d_row["name_en"]])
                }

            # 6. Urban Local Body Match
            cur.execute("""
                SELECT ulb.*, d.name_en AS district_name, div.name_en AS division_name
                FROM urban_local_bodies ulb
                LEFT JOIN districts d ON ulb.district_id = d.id
                LEFT JOIN divisions div ON d.division_id = div.id
                WHERE ulb.name_en ILIKE %s OR ulb.name_hi ILIKE %s OR ulb.city_name ILIKE %s LIMIT 1;
            """, (sterm, sterm, sterm))
            ulb_row = cur.fetchone()
            if ulb_row:
                return {
                    "matched": True,
                    "entity_type": f"Urban Local Body ({ulb_row['ulb_type']})",
                    "entity_name": ulb_row["name_en"],
                    "lineage": {
                        "state": "Rajasthan",
                        "division": ulb_row["division_name"],
                        "district": ulb_row["district_name"],
                        "city": ulb_row["city_name"],
                        "ulb_name": ulb_row["name_en"],
                        "ulb_type": ulb_row["ulb_type"],
                        "pincode": ulb_row["pincode"],
                        "lgd_code": ulb_row["lgd_code"]
                    },
                    "breadcrumbs": _clean_breadcrumbs(["Rajasthan", ulb_row["division_name"], ulb_row["district_name"], ulb_row["name_en"]])
                }

            # 7. Division Match
            cur.execute("""
                SELECT div.*, 
                       (SELECT json_agg(d.name_en) FROM districts d WHERE d.division_id = div.id) AS districts_list
                FROM divisions div
                WHERE div.name_en ILIKE %s OR div.name_hi ILIKE %s LIMIT 1;
            """, (sterm, sterm))
            div_row = cur.fetchone()
            if div_row:
                return {
                    "matched": True,
                    "entity_type": "Division",
                    "entity_name": div_row["name_en"],
                    "lineage": {
                        "state": "Rajasthan",
                        "division": div_row["name_en"],
                        "divisional_commissioner": div_row["divisional_commissioner"],
                        "districts": div_row["districts_list"] or [],
                        "lgd_code": div_row["lgd_code"]
                    },
                    "breadcrumbs": _clean_breadcrumbs(["Rajasthan", div_row["name_en"]])
                }

            return {
                "matched": False,
                "query": term,
                "message": f"Entity '{term}' not found in Rajasthan master hierarchy tables."
            }


def tool_get_database_stats() -> Dict[str, Any]:
    """Summary counts of administrative entities across all 6 Rajasthan tiers."""
    tables = [
        "states", "divisions", "districts", "sub_divisions", "tehsils_blocks",
        "gram_panchayats", "panchayat_wards", "villages", "urban_local_bodies",
        "urban_wards", "pincodes", "chat_logs", "scraper_runs"
    ]
    counts = {}
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for t in tables:
                cur.execute(f"SELECT count(*) AS cnt FROM {t};")
                counts[t] = cur.fetchone()["cnt"]

    return {
        "status": "healthy",
        "database": DB_NAME,
        "counts": counts,
        "summary": {
            "tier_1_state": counts.get("states", 0),
            "tier_2_divisions": counts.get("divisions", 0),
            "tier_3_districts": counts.get("districts", 0),
            "tier_4_sub_divisions": counts.get("sub_divisions", 0),
            "tier_5_tehsils_blocks": counts.get("tehsils_blocks", 0),
            "tier_6_rural_villages_gps": counts.get("villages", 0) + counts.get("gram_panchayats", 0),
            "tier_6_urban_bodies": counts.get("urban_local_bodies", 0),
            "postal_directory_pincodes": counts.get("pincodes", 0)
        }
    }


# =====================================================================
# MCP Tool Metadata & Registry
# =====================================================================

MCP_TOOLS = [
    {
        "name": "list_tables",
        "description": "Lists all user tables in finalairajmaster PostgreSQL database with row counts and column counts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "describe_table",
        "description": "Describes the column schema, types, nullable status, and primary keys of a specific table in PostgreSQL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "The exact name of the table to describe (e.g. 'districts', 'divisions', 'villages')"
                }
            },
            "required": ["table_name"]
        }
    },
    {
        "name": "read_query",
        "description": "Executes a safe read-only SQL query (SELECT, WITH, EXPLAIN, SHOW) against the finalairajmaster PostgreSQL database and returns structured rows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SQL query to execute (must start with SELECT, WITH, EXPLAIN, or SHOW)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return (default 100)",
                    "default": 100
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_administrative_lineage",
        "description": "Reconstructs the full 6-tier Rajasthan administrative lineage from PostgreSQL tables for any location name, district, tehsil, village, or pincode.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_name_or_pincode": {
                    "type": "string",
                    "description": "Location name (e.g. 'Muhana', 'Balotra', 'Sanganer') or 6-digit Pincode (e.g. '302029')"
                }
            },
            "required": ["entity_name_or_pincode"]
        }
    },
    {
        "name": "get_database_stats",
        "description": "Returns counts of records across all 6 administrative tiers (divisions, districts, tehsils, villages, pincodes) in PostgreSQL.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


def execute_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Dispatches execution to the appropriate tool function."""
    if name == "list_tables":
        return tool_list_tables()
    elif name == "describe_table":
        table_name = arguments.get("table_name")
        if not table_name:
            raise ValueError("Argument 'table_name' is required.")
        return tool_describe_table(table_name)
    elif name == "read_query":
        query = arguments.get("query")
        if not query:
            raise ValueError("Argument 'query' is required.")
        limit = arguments.get("limit", 100)
        return tool_read_query(query, limit)
    elif name == "get_administrative_lineage":
        entity = arguments.get("entity_name_or_pincode")
        if not entity:
            raise ValueError("Argument 'entity_name_or_pincode' is required.")
        return tool_get_administrative_lineage(entity)
    elif name == "get_database_stats":
        return tool_get_database_stats()
    else:
        raise ValueError(f"Unknown tool: '{name}'")


# =====================================================================
# JSON-RPC 2.0 MCP Stdio Server Protocol Loop
# =====================================================================

def handle_json_rpc_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Handles an incoming JSON-RPC 2.0 message according to MCP 2024-11-05 spec."""
    msg_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {})

    # 1. Notification (no id)
    if msg_id is None:
        if method == "notifications/initialized":
            logger.info("MCP client notification: initialized.")
        return None

    # 2. Handshake / Initialize
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": False
                    },
                    "resources": {
                        "subscribe": False,
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": "finalairajmaster-postgres-mcp",
                    "version": "1.0.0"
                }
            }
        }

    # 3. Ping
    if method == "ping":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {}
        }

    # 4. Tools List
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": MCP_TOOLS
            }
        }

    # 5. Tools Call
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            res = execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(res, indent=2, default=str)
                        }
                    ],
                    "isError": False
                }
            }
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {str(e)}"
                        }
                    ],
                    "isError": True
                }
            }

    # 6. Resources List
    if method == "resources/list":
        try:
            tables_data = tool_list_tables()
            resources = [
                {
                    "uri": f"postgres://finalairajmaster/{t['table_name']}",
                    "name": f"PostgreSQL Table: {t['table_name']}",
                    "description": f"Table '{t['table_name']}' with {t['row_count']} rows",
                    "mimeType": "application/json"
                }
                for t in tables_data["tables"]
            ]
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "resources": resources
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {
            "code": -32601,
            "message": f"Method '{method}' not implemented."
        }
    }


def run_stdio_server():
    """Runs the MCP server over standard I/O."""
    logger.info("Starting finalairajmaster PostgreSQL MCP Server on stdio...")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_json_rpc_message(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error: Invalid JSON."}
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"Unexpected loop exception: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Testing PostgreSQL MCP tools directly:")
        print("1. list_tables:", tool_list_tables()["total_tables"], "tables found.")
        print("2. describe_table (districts):", len(tool_describe_table("districts")["columns"]), "columns.")
        print("3. read_query (divisions):", tool_read_query("SELECT id, name_en FROM divisions LIMIT 3;")["row_count"], "rows.")
        print("4. lineage (Muhana):", tool_get_administrative_lineage("Muhana")["entity_name"])
        print("5. stats:", tool_get_database_stats()["summary"])
        print("ALL SELF-TESTS PASSED!")
    else:
        run_stdio_server()
