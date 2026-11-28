"""
Styled Excel (.xlsx) & Multilingual PDF (.pdf) Export Generators
for Admin Dashboard (all tabs + charts) and Public Chat Transcripts.
"""
import io
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from fpdf import FPDF


# ---------------------------------------------------------------------------
# Color Palette (Rajasthan Governance Saffron & Slate Theme)
# ---------------------------------------------------------------------------
NAVY = "1E293B"
SAFFRON = "EA580C"
AMBER = "D97706"
EMERALD = "059669"
INDIGO = "4F46E5"
WHITE = "FFFFFF"
LIGHT_PEACH = "FFF7ED"
LIGHT_SLATE = "F8FAFC"
BORDER_GRAY = "CBD5E1"
EMERALD_BG = "DCFCE7"
EMERALD_FG = "166534"
BLUE_BG = "DBEAFE"
BLUE_FG = "1E40AF"
RED_BG = "FEE2E2"
RED_FG = "991B1B"
AMBER_BG = "FEF3C7"
AMBER_FG = "92400E"

THIN_BORDER = Border(
    left=Side(style="thin", color=BORDER_GRAY),
    right=Side(style="thin", color=BORDER_GRAY),
    top=Side(style="thin", color=BORDER_GRAY),
    bottom=Side(style="thin", color=BORDER_GRAY),
)


def _fill(hex_color: str) -> PatternFill:
    return PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")


def _font(size: int = 10, bold: bool = False, color: str = "0F172A") -> Font:
    return Font(name="Calibri", size=size, bold=bold, color=color)


def _clean_text(val: Any, max_len: int = 12000) -> str:
    if val is None:
        return ""
    s = str(val).replace("\r\n", "\n").replace("\r", "\n")
    # Remove Excel-illegal ASCII control chars (keep \n and \t)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def _style_banner(ws, title: str, subtitle: str, col_count: int = 8, accent: str = SAFFRON) -> int:
    end_col = get_column_letter(max(col_count, 2))
    ws.merge_cells(f"A1:{end_col}1")
    ws.merge_cells(f"A2:{end_col}2")
    c1 = ws["A1"]
    c1.value = title
    c1.font = Font(name="Calibri", size=15, bold=True, color=WHITE)
    c1.fill = _fill(NAVY)
    c1.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 32

    c2 = ws["A2"]
    c2.value = subtitle
    c2.font = Font(name="Calibri", size=10, italic=True, color=WHITE)
    c2.fill = _fill(accent)
    c2.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 22
    ws.row_dimensions[3].height = 8
    return 4


def _style_table_header(ws, row_idx: int, headers: List[str], bg: str = NAVY) -> None:
    ws.row_dimensions[row_idx].height = 24
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row_idx, column=col_idx, value=h)
        cell.font = _font(10, bold=True, color=WHITE)
        cell.fill = _fill(bg)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER


def _auto_fit_columns(ws, col_widths: Optional[Dict[int, int]] = None, min_w: int = 12, max_w: int = 52) -> None:
    col_widths = col_widths or {}
    for col in ws.columns:
        col_idx = col[0].column
        if col_idx in col_widths:
            ws.column_dimensions[get_column_letter(col_idx)].width = col_widths[col_idx]
            continue
        best = min_w
        for cell in col[:250]:
            if cell.row <= 2:
                continue
            val = str(cell.value or "")
            longest_line = max((len(line) for line in val.split("\n")), default=0)
            best = max(best, min(longest_line + 4, max_w))
        ws.column_dimensions[get_column_letter(col_idx)].width = best


def _write_kpi_strip(ws, start_row: int, kpis: List[Dict[str, Any]]) -> int:
    """Renders colorful KPI summary tiles across pairs of columns."""
    ws.row_dimensions[start_row].height = 18
    ws.row_dimensions[start_row + 1].height = 28
    palette = [SAFFRON, INDIGO, EMERALD, AMBER, NAVY, "0284C7"]
    col = 1
    for idx, k in enumerate(kpis):
        color = k.get("color") or palette[idx % len(palette)]
        lbl = ws.cell(row=start_row, column=col, value=k["label"])
        lbl.font = _font(9, bold=True, color=WHITE)
        lbl.fill = _fill(color)
        lbl.alignment = Alignment(horizontal="center", vertical="center")
        lbl.border = THIN_BORDER

        val = ws.cell(row=start_row + 1, column=col, value=k["value"])
        val.font = _font(13, bold=True, color=NAVY)
        val.fill = _fill(LIGHT_PEACH if idx % 2 == 0 else LIGHT_SLATE)
        val.alignment = Alignment(horizontal="center", vertical="center")
        val.border = THIN_BORDER
        if isinstance(k["value"], int):
            val.number_format = "#,##0"
        col += 1
    ws.row_dimensions[start_row + 2].height = 10
    return start_row + 3


# ---------------------------------------------------------------------------
# ADMIN DASHBOARD MULTI-TAB WORKBOOK BUILDER
# ---------------------------------------------------------------------------
def build_admin_excel(tab: str, payload: Dict[str, Any]) -> bytes:
    """
    Generates a richly styled, multi-sheet Excel workbook with KPI strips,
    status badges, formulas, and native Excel Bar/Pie charts across Admin tabs:
      tab in ('all', 'llm', 'scraper', 'database', 'logs')
    """
    wb = Workbook()
    # Remove default sheet after creating custom ones cleanly
    default_ws = wb.active

    tab_norm = (tab or "all").lower().strip()
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    stats = payload.get("stats") or {}
    llm = payload.get("llm_config") or {}
    runs = payload.get("scraper_runs") or []
    logs = payload.get("chat_logs") or []
    geo_records = payload.get("geo_records") or []
    geo_level = payload.get("geo_level") or "all"
    geo_total = payload.get("geo_total", len(geo_records))
    div_dist_summary = payload.get("div_dist_summary") or []
    pincode_localities_count = payload.get("pincode_localities_count", 53967)
    portal_totals = payload.get("portal_totals") or {
        "Divisions": 10,
        "Districts": 50,
        "Sub-Divisions": 328,
        "Tehsils / Blocks": 883,
        "Gram Panchayats": 14496,
        "Revenue Villages": 51892,
        "Urban Bodies (ULB)": 309,
        "Urban Wards": 10245,
        "Pincodes": 1000,
    }

    # =======================================================================
    # 1. EXECUTIVE SUMMARY SHEET (always first on 'all', and summary on 'database')
    # =======================================================================
    if tab_norm in ("all", "database"):
        ws_sum = wb.create_sheet("Executive Summary")
        ws_sum.views.sheetView[0].showGridLines = True
        r = _style_banner(
            ws_sum,
            "Rajasthan Geographic & Administrative Master — Executive Summary",
            f"Generated: {now_str}  |  PostgreSQL Live Snapshot  |  Total Geographic Records: {stats.get('total_entities', 0):,} (+{pincode_localities_count:,} Postal Localities)",
            col_count=6,
            accent=SAFFRON,
        )
        r = _write_kpi_strip(
            ws_sum,
            r,
            [
                {"label": "Total Master Entities", "value": int(stats.get("total_entities", 0)), "color": SAFFRON},
                {"label": "Revenue Villages", "value": int(stats.get("villages", 0)), "color": EMERALD},
                {"label": "Gram Panchayats", "value": int(stats.get("gram_panchayats", 0)), "color": INDIGO},
                {"label": "Urban Wards", "value": int(stats.get("urban_wards", 0)), "color": "0284C7"},
                {"label": "Pincode Localities", "value": int(pincode_localities_count), "color": AMBER},
                {"label": "Logged Chats", "value": len(logs), "color": NAVY},
            ],
        )

        # Hierarchy Coverage Table
        headers = ["Tier #", "Administrative Level", "Local DB Count", "Official Portal Target", "Coverage %", "Governance Authority"]
        _style_table_header(ws_sum, r, headers, bg=NAVY)
        tier_rows = [
            (1, "Divisions", int(stats.get("divisions", 0)), portal_totals.get("Divisions", 10), "Divisional Commissioner"),
            (2, "Districts", int(stats.get("districts", 0)), portal_totals.get("Districts", 50), "District Collectorate & Zila Parishad"),
            (3, "Sub-Divisions", int(stats.get("sub_divisions", 0)), portal_totals.get("Sub-Divisions", 328), "Sub-Divisional Magistrate (SDM/SDO)"),
            (4, "Tehsils / Blocks", int(stats.get("tehsils_blocks", 0)), portal_totals.get("Tehsils / Blocks", 883), "Tehsildar (Revenue) & BDO (Block)"),
            (5, "Gram Panchayats", int(stats.get("gram_panchayats", 0)), portal_totals.get("Gram Panchayats", 14496), "Sarpanch & VDO"),
            (6, "Revenue Villages", int(stats.get("villages", 0)), portal_totals.get("Revenue Villages", 51892), "Patwari & ILR Circle"),
            (7, "Urban Bodies (ULB)", int(stats.get("urban_local_bodies", 0)), portal_totals.get("Urban Bodies (ULB)", 309), "Mayor / Chairman / EO"),
            (8, "Urban Wards", int(stats.get("urban_wards", 0)), portal_totals.get("Urban Wards", 10245), "Ward Councillor / Parshad"),
            (9, "Pincodes (Unique Codes)", int(stats.get("pincodes", 0)), portal_totals.get("Pincodes", 1000), f"India Post ({pincode_localities_count:,} Localities)"),
        ]

        data_start = r + 1
        for idx, (tier_no, lvl_name, db_cnt, target_cnt, auth_str) in enumerate(tier_rows):
            row_i = data_start + idx
            ws_sum.row_dimensions[row_i].height = 21
            bg = LIGHT_PEACH if idx % 2 == 0 else LIGHT_SLATE
            vals = [tier_no, lvl_name, db_cnt, target_cnt, f"=IF(D{row_i}>0,MIN(1,C{row_i}/D{row_i}),1)", auth_str]
            for c_i, val in enumerate(vals, start=1):
                cell = ws_sum.cell(row=row_i, column=c_i, value=val)
                cell.font = _font(10, bold=(c_i in (2, 3)))
                cell.fill = _fill(bg)
                cell.border = THIN_BORDER
                if c_i in (3, 4):
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif c_i == 5:
                    cell.number_format = "0.0%"
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.fill = _fill(EMERALD_BG if db_cnt >= target_cnt else AMBER_BG)
                    cell.font = _font(10, bold=True, color=EMERALD_FG if db_cnt >= target_cnt else AMBER_FG)
                elif c_i == 1:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        data_end = data_start + len(tier_rows) - 1
        tot_row = data_end + 1
        ws_sum.row_dimensions[tot_row].height = 23
        tot_vals = ["", "TOTAL GEOGRAPHIC ENTITIES", f"=SUM(C{data_start}:C{data_end})", f"=SUM(D{data_start}:D{data_end})", f"=C{tot_row}/D{tot_row}", "All 6 Governance Tiers"]
        for c_i, val in enumerate(tot_vals, start=1):
            cell = ws_sum.cell(row=tot_row, column=c_i, value=val)
            cell.font = _font(10, bold=True, color=WHITE)
            cell.fill = _fill(NAVY)
            cell.border = THIN_BORDER
            if c_i in (3, 4):
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif c_i == 5:
                cell.number_format = "0.0%"
                cell.alignment = Alignment(horizontal="center", vertical="center")

        # Native Chart 1: Local DB vs Target Bar Chart (placed cleanly below table)
        chart_row = tot_row + 2
        bar = BarChart()
        bar.type = "col"
        bar.style = 10
        bar.title = "Rajasthan Administrative Tiers — Local DB Count vs Official Portal Target"
        bar.y_axis.title = "Record Count"
        bar.x_axis.title = "Geographic Tier"
        data_ref = Reference(ws_sum, min_col=3, max_col=4, min_row=r, max_row=data_end)
        cats_ref = Reference(ws_sum, min_col=2, min_row=data_start, max_row=data_end)
        bar.add_data(data_ref, titles_from_data=True)
        bar.set_categories(cats_ref)
        bar.width = 22
        bar.height = 11
        if len(bar.series) >= 2:
            bar.series[0].graphicalProperties.solidFill = SAFFRON
            bar.series[1].graphicalProperties.solidFill = "334155"
        ws_sum.add_chart(bar, f"A{chart_row}")

        # District-wise Breakdown table & Pie chart on right side if provided
        if div_dist_summary:
            dist_hdr_row = r
            ws_sum.cell(row=dist_hdr_row, column=8, value="Top Districts by Villages").font = _font(10, bold=True, color=WHITE)
            ws_sum.cell(row=dist_hdr_row, column=8).fill = _fill(SAFFRON)
            ws_sum.cell(row=dist_hdr_row, column=8).border = THIN_BORDER
            ws_sum.cell(row=dist_hdr_row, column=9, value="Villages").font = _font(10, bold=True, color=WHITE)
            ws_sum.cell(row=dist_hdr_row, column=9).fill = _fill(SAFFRON)
            ws_sum.cell(row=dist_hdr_row, column=9).border = THIN_BORDER
            ws_sum.cell(row=dist_hdr_row, column=10, value="GPs").font = _font(10, bold=True, color=WHITE)
            ws_sum.cell(row=dist_hdr_row, column=10).fill = _fill(SAFFRON)
            ws_sum.cell(row=dist_hdr_row, column=10).border = THIN_BORDER
            for d_i, ds in enumerate(div_dist_summary[:10]):
                dr = dist_hdr_row + 1 + d_i
                for c_off, val in enumerate([ds["district"], ds["villages"], ds["gps"]]):
                    c = ws_sum.cell(row=dr, column=8 + c_off, value=val)
                    c.font = _font(9, bold=(c_off == 0))
                    c.fill = _fill(LIGHT_PEACH if d_i % 2 == 0 else LIGHT_SLATE)
                    c.border = THIN_BORDER
                    if c_off > 0:
                        c.number_format = "#,##0"

            pie = PieChart()
            pie.title = "Top 10 Districts — Village Share"
            pie.add_data(Reference(ws_sum, min_col=9, min_row=dist_hdr_row, max_row=dist_hdr_row + min(len(div_dist_summary), 10)), titles_from_data=True)
            pie.set_categories(Reference(ws_sum, min_col=8, min_row=dist_hdr_row + 1, max_row=dist_hdr_row + min(len(div_dist_summary), 10)))
            pie.width = 14
            pie.height = 11
            ws_sum.add_chart(pie, f"H{chart_row}")

        _auto_fit_columns(ws_sum, {1: 9, 2: 26, 3: 16, 4: 22, 5: 14, 6: 36, 7: 4, 8: 22, 9: 12, 10: 10})
        ws_sum.freeze_panes = f"A{data_start}"

    # =======================================================================
    # 2. LLM & AI CONTROL SHEET
    # =======================================================================
    if tab_norm in ("all", "llm"):
        ws_llm = wb.create_sheet("LLM & AI Control")
        r = _style_banner(
            ws_llm,
            "LLM & AI Control Configuration Report",
            f"Active Model: {llm.get('active_model', 'N/A')}  |  Endpoint: {llm.get('ollama_base_url', '')}  |  Exported: {now_str}",
            col_count=4,
            accent=INDIGO,
        )
        r = _write_kpi_strip(
            ws_llm,
            r,
            [
                {"label": "Active Model", "value": str(llm.get("active_model", "N/A")), "color": INDIGO},
                {"label": "Temperature", "value": float(llm.get("temperature", 0.2)), "color": SAFFRON},
                {"label": "Max Tokens", "value": int(llm.get("max_tokens", 1024)), "color": EMERALD},
                {"label": "Support Phone", "value": str(llm.get("support_phone", "")), "color": NAVY},
            ],
        )
        _style_table_header(ws_llm, r, ["Category", "Parameter Key", "Configured Value", "Notes"], bg=NAVY)
        cfg_rows = [
            ("Model Engine", "Active Ollama / LLM Model", llm.get("active_model"), "Primary inference model selected in Admin"),
            ("Model Engine", "Ollama Base URL", llm.get("ollama_base_url"), "Local / Container inference endpoint"),
            ("Model Engine", "Available Detected Models", ", ".join(llm.get("available_models") or []), "Models currently available for failover"),
            ("Generation", "Temperature", llm.get("temperature"), "Lower values enforce strict deterministic facts"),
            ("Generation", "Max Output Tokens", llm.get("max_tokens"), "Maximum token budget per reply"),
            ("RAG & Search", "Vector RAG Enabled", "Enabled" if llm.get("enable_rag", True) else "Disabled", f"Top-K chunks: {llm.get('rag_top_k', 5)}"),
            ("RAG & Search", "Live Web Search Enabled", "Enabled" if llm.get("enable_web_search", True) else "Disabled", f"Provider: {llm.get('web_search_provider', 'duckduckgo')} (max {llm.get('web_search_max_results', 4)})"),
            ("Citizen Support", "Official Helpline Phone", llm.get("support_phone"), "Displayed on out-of-scope guardrail cards"),
            ("Prompts", "Welcome Greeting", _clean_text(llm.get("greeting_message")), "Shown on public chat initialization"),
            ("Prompts", "Agent System Prompt", _clean_text(llm.get("system_prompt")), "Master guardrail & formatting rules"),
        ]
        for idx, row_vals in enumerate(cfg_rows):
            ri = r + 1 + idx
            is_long = len(str(row_vals[2] or "")) > 80
            ws_llm.row_dimensions[ri].height = 68 if is_long else 22
            bg = LIGHT_SLATE if idx % 2 == 0 else WHITE
            for ci, val in enumerate(row_vals, start=1):
                c = ws_llm.cell(row=ri, column=ci, value=val)
                c.font = _font(10, bold=(ci == 2))
                c.fill = _fill(bg)
                c.border = THIN_BORDER
                c.alignment = Alignment(horizontal="left", vertical="top" if is_long else "center", wrap_text=True)
        _auto_fit_columns(ws_llm, {1: 18, 2: 28, 3: 56, 4: 38})
        ws_llm.freeze_panes = f"A{r + 1}"

    # =======================================================================
    # 3. RAJMASTER SCRAPER ETL SHEET
    # =======================================================================
    if tab_norm in ("all", "scraper"):
        ws_scr = wb.create_sheet("RajMaster Scraper ETL")
        total_fetched = sum(int(x.get("rows_fetched") or 0) for x in runs)
        total_upserted = sum(int(x.get("rows_upserted") or 0) for x in runs)
        completed_runs = sum(1 for x in runs if str(x.get("status", "")).lower() == "completed")
        r = _style_banner(
            ws_scr,
            "RajMaster Scraper & ETL Synchronization Report",
            f"Source: https://rajmasters.rajasthan.gov.in  |  Total Logged Runs: {len(runs)}  |  Exported: {now_str}",
            col_count=7,
            accent=EMERALD,
        )
        r = _write_kpi_strip(
            ws_scr,
            r,
            [
                {"label": "Total Scraper Runs", "value": len(runs), "color": NAVY},
                {"label": "Completed Runs", "value": completed_runs, "color": EMERALD},
                {"label": "Total Rows Fetched", "value": total_fetched, "color": SAFFRON},
                {"label": "Total Rows Upserted", "value": total_upserted, "color": INDIGO},
            ],
        )
        _style_table_header(ws_scr, r, ["Run ID", "Master Target", "Status", "Rows Fetched", "Rows Upserted", "Started At", "Completed / Notice"], bg=NAVY)
        s_start = r + 1
        for idx, run in enumerate(runs):
            ri = s_start + idx
            ws_scr.row_dimensions[ri].height = 21
            status_str = str(run.get("status") or "").lower()
            bg = LIGHT_PEACH if idx % 2 == 0 else LIGHT_SLATE
            row_vals = [
                run.get("id"),
                run.get("master_name"),
                status_str.upper(),
                int(run.get("rows_fetched") or 0),
                int(run.get("rows_upserted") or 0),
                _clean_text(run.get("started_at")),
                _clean_text(run.get("error_logs") or run.get("completed_at") or "Clean sync"),
            ]
            for ci, val in enumerate(row_vals, start=1):
                c = ws_scr.cell(row=ri, column=ci, value=val)
                c.font = _font(10, bold=(ci in (2, 3)))
                c.fill = _fill(bg)
                c.border = THIN_BORDER
                if ci in (4, 5):
                    c.number_format = "#,##0"
                    c.alignment = Alignment(horizontal="right", vertical="center")
                elif ci == 3:
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    if status_str == "completed":
                        c.fill = _fill(EMERALD_BG)
                        c.font = _font(10, bold=True, color=EMERALD_FG)
                    elif status_str == "failed":
                        c.fill = _fill(RED_BG)
                        c.font = _font(10, bold=True, color=RED_FG)
                    else:
                        c.fill = _fill(AMBER_BG)
                        c.font = _font(10, bold=True, color=AMBER_FG)
                else:
                    c.alignment = Alignment(horizontal="left", vertical="center")

        if runs:
            chart_end = min(s_start + len(runs) - 1, s_start + 14)
            s_bar = BarChart()
            s_bar.type = "col"
            s_bar.style = 11
            s_bar.title = "Recent Scraper Runs — Fetched vs Upserted Rows"
            s_bar.add_data(Reference(ws_scr, min_col=4, max_col=5, min_row=r, max_row=chart_end), titles_from_data=True)
            s_bar.set_categories(Reference(ws_scr, min_col=2, min_row=s_start, max_row=chart_end))
            s_bar.width = 22
            s_bar.height = 10
            ws_scr.add_chart(s_bar, f"A{s_start + len(runs) + 2}")

        ws_scr.auto_filter.ref = f"A{r}:G{max(r, s_start + len(runs) - 1)}"
        ws_scr.freeze_panes = f"A{s_start}"
        _auto_fit_columns(ws_scr, {1: 10, 2: 34, 3: 14, 4: 15, 5: 15, 6: 24, 7: 38})

    # =======================================================================
    # 4. GEOGRAPHIC RECORDS SHEET
    # =======================================================================
    if tab_norm in ("all", "database"):
        sheet_title = f"Geo Records ({geo_level[:18]})" if tab_norm == "database" else "Geographic Records"
        ws_geo = wb.create_sheet(sheet_title)
        note = ""
        if geo_total > len(geo_records):
            note = f"  |  Showing top {len(geo_records):,} of {geo_total:,} matching rows (use Search/Filter for targeted subsets)"
        r = _style_banner(
            ws_geo,
            f"Rajasthan Geographic Master Directory — Tier: {geo_level.upper()}",
            f"Matched DB Total: {geo_total:,}  |  Exported Rows: {len(geo_records):,}{note}",
            col_count=9,
            accent=SAFFRON,
        )
        _style_table_header(
            ws_geo,
            r,
            ["ID", "Tier / Level", "Name (English)", "Name (Hindi)", "Code", "LGD Code", "Parent Entity", "Governance / Authority", "Pincode / Type"],
            bg=NAVY,
        )
        g_start = r + 1
        for idx, rec in enumerate(geo_records):
            ri = g_start + idx
            ws_geo.row_dimensions[ri].height = 20
            bg = LIGHT_PEACH if idx % 2 == 0 else LIGHT_SLATE
            row_vals = [
                rec.get("id"),
                rec.get("level"),
                _clean_text(rec.get("name_en")),
                _clean_text(rec.get("name_hi")),
                _clean_text(rec.get("code")),
                rec.get("lgd_code"),
                _clean_text(rec.get("parent_name")),
                _clean_text(rec.get("authority_details")),
                _clean_text(rec.get("pincode") or rec.get("extra_type")),
            ]
            for ci, val in enumerate(row_vals, start=1):
                c = ws_geo.cell(row=ri, column=ci, value=val)
                c.font = _font(10, bold=(ci == 3))
                c.fill = _fill(bg)
                c.border = THIN_BORDER
                c.alignment = Alignment(horizontal="center" if ci in (1, 5, 6) else "left", vertical="center")
        ws_geo.auto_filter.ref = f"A{r}:I{max(r, g_start + len(geo_records) - 1)}"
        ws_geo.freeze_panes = f"A{g_start}"
        _auto_fit_columns(ws_geo, {1: 9, 2: 16, 3: 28, 4: 26, 5: 14, 6: 12, 7: 30, 8: 36, 9: 18})

    # =======================================================================
    # 5. CHAT & HELPLINE LOGS SHEET
    # =======================================================================
    if tab_norm in ("all", "logs"):
        ws_logs = wb.create_sheet("Chat & Helpline Logs")
        intent_counts: Dict[str, int] = {}
        lat_vals = [int(x.get("latency_ms") or 0) for x in logs]
        for lg in logs:
            it = str(lg.get("detected_intent") or "unknown")
            intent_counts[it] = intent_counts.get(it, 0) + 1
        avg_lat = round(sum(lat_vals) / len(lat_vals), 1) if lat_vals else 0

        r = _style_banner(
            ws_logs,
            "Citizen Chat & Helpline Telemetry Logs",
            f"Total Exported Logs: {len(logs):,}  |  Average Latency: {avg_lat} ms  |  Exported: {now_str}",
            col_count=7,
            accent=NAVY,
        )
        r = _write_kpi_strip(
            ws_logs,
            r,
            [
                {"label": "Total Interactions", "value": len(logs), "color": NAVY},
                {"label": "Geographic Queries", "value": intent_counts.get("geographic_query", 0), "color": EMERALD},
                {"label": "Capability Queries", "value": intent_counts.get("capability_query", 0), "color": INDIGO},
                {"label": "Out-of-Scope (Helpline)", "value": intent_counts.get("out_of_scope", 0), "color": SAFFRON},
                {"label": "Avg Latency (ms)", "value": avg_lat, "color": AMBER},
            ],
        )

        # Mini Intent Summary table & Pie chart at top right of Logs sheet
        ic_row = r
        _style_table_header(ws_logs, ic_row, ["Log ID", "Session ID", "User Query", "Detected Intent", "Latency (ms)", "AI Response", "Timestamp"], bg=NAVY)
        l_start = ic_row + 1
        for idx, lg in enumerate(logs):
            ri = l_start + idx
            resp_txt = _clean_text(lg.get("ai_response"), max_len=2000)
            ws_logs.row_dimensions[ri].height = 48 if len(resp_txt) > 120 else 24
            bg = LIGHT_SLATE if idx % 2 == 0 else WHITE
            intent_s = str(lg.get("detected_intent") or "unknown")
            row_vals = [
                lg.get("id"),
                _clean_text(lg.get("session_id")),
                _clean_text(lg.get("user_query"), max_len=500),
                intent_s,
                int(lg.get("latency_ms") or 0),
                resp_txt,
                _clean_text(lg.get("created_at")),
            ]
            for ci, val in enumerate(row_vals, start=1):
                c = ws_logs.cell(row=ri, column=ci, value=val)
                c.font = _font(10, bold=(ci in (3, 4)))
                c.fill = _fill(bg)
                c.border = THIN_BORDER
                c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
                if ci == 4:
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    if intent_s == "geographic_query":
                        c.fill = _fill(EMERALD_BG)
                        c.font = _font(9, bold=True, color=EMERALD_FG)
                    elif intent_s == "out_of_scope":
                        c.fill = _fill(RED_BG)
                        c.font = _font(9, bold=True, color=RED_FG)
                    else:
                        c.fill = _fill(BLUE_BG)
                        c.font = _font(9, bold=True, color=BLUE_FG)
                elif ci in (1, 5):
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    if ci == 5:
                        c.number_format = "#,##0"

        # Add small Intent Breakdown block + PieChart in columns I-J
        if intent_counts:
            ws_logs.cell(row=ic_row, column=9, value="Intent Type").font = _font(10, bold=True, color=WHITE)
            ws_logs.cell(row=ic_row, column=9).fill = _fill(SAFFRON)
            ws_logs.cell(row=ic_row, column=9).border = THIN_BORDER
            ws_logs.cell(row=ic_row, column=10, value="Count").font = _font(10, bold=True, color=WHITE)
            ws_logs.cell(row=ic_row, column=10).fill = _fill(SAFFRON)
            ws_logs.cell(row=ic_row, column=10).border = THIN_BORDER
            for i_idx, (ik, iv) in enumerate(intent_counts.items()):
                ir = ic_row + 1 + i_idx
                ws_logs.cell(row=ir, column=9, value=ik).border = THIN_BORDER
                ws_logs.cell(row=ir, column=10, value=iv).border = THIN_BORDER
            l_pie = PieChart()
            l_pie.title = "Chat Intent Distribution"
            l_pie.add_data(Reference(ws_logs, min_col=10, min_row=ic_row, max_row=ic_row + len(intent_counts)), titles_from_data=True)
            l_pie.set_categories(Reference(ws_logs, min_col=9, min_row=ic_row + 1, max_row=ic_row + len(intent_counts)))
            l_pie.width = 13
            l_pie.height = 9
            ws_logs.add_chart(l_pie, f"I{ic_row + len(intent_counts) + 2}")

        ws_logs.auto_filter.ref = f"A{ic_row}:G{max(ic_row, l_start + len(logs) - 1)}"
        ws_logs.freeze_panes = f"A{l_start}"
        _auto_fit_columns(ws_logs, {1: 10, 2: 20, 3: 38, 4: 18, 5: 13, 6: 58, 7: 22, 8: 4, 9: 22, 10: 10})

    if default_ws in wb.worksheets and len(wb.worksheets) > 1:
        wb.remove(default_ws)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PUBLIC CHAT EXPORT: EXCEL (.xlsx)
# ---------------------------------------------------------------------------
def build_chat_excel(
    session_id: str,
    messages: List[Dict[str, Any]],
    language: str = "en",
    support_phone: str = "89988555525",
) -> bytes:
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Session Summary"
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

    user_msgs = [m for m in messages if m.get("sender") == "user"]
    bot_msgs = [m for m in messages if m.get("sender") != "user"]
    intents: Dict[str, int] = {}
    for m in bot_msgs:
        it = str(m.get("intent") or "general")
        intents[it] = intents.get(it, 0) + 1

    r = _style_banner(
        ws_sum,
        "RajMaster AI — Citizen Chat Conversation Summary",
        f"Session ID: {session_id}  |  Language: {language.upper()}  |  Exported: {now_str}  |  Helpline: {support_phone}",
        col_count=5,
        accent=SAFFRON,
    )
    r = _write_kpi_strip(
        ws_sum,
        r,
        [
            {"label": "Total Messages", "value": len(messages), "color": NAVY},
            {"label": "User Questions", "value": len(user_msgs), "color": SAFFRON},
            {"label": "AI Replies", "value": len(bot_msgs), "color": EMERALD},
            {"label": "Session Language", "value": language.upper(), "color": INDIGO},
        ],
    )

    _style_table_header(ws_sum, r, ["Intent Category", "Replies Count", "Share %"], bg=NAVY)
    if not intents:
        intents = {"session": len(bot_msgs)}
    start_i = r + 1
    for idx, (ik, cnt) in enumerate(intents.items()):
        ri = start_i + idx
        ws_sum.row_dimensions[ri].height = 21
        ws_sum.cell(row=ri, column=1, value=ik.replace("_", " ").title()).border = THIN_BORDER
        c2 = ws_sum.cell(row=ri, column=2, value=cnt)
        c2.number_format = "#,##0"
        c2.border = THIN_BORDER
        tot_ref = max(len(bot_msgs), 1)
        c3 = ws_sum.cell(row=ri, column=3, value=cnt / tot_ref)
        c3.number_format = "0.0%"
        c3.border = THIN_BORDER

    pie = PieChart()
    pie.title = "Conversation Intent Breakdown"
    pie.add_data(Reference(ws_sum, min_col=2, min_row=r, max_row=r + len(intents)), titles_from_data=True)
    pie.set_categories(Reference(ws_sum, min_col=1, min_row=start_i, max_row=r + len(intents)))
    pie.width = 14
    pie.height = 9
    ws_sum.add_chart(pie, f"E{r}")
    _auto_fit_columns(ws_sum, {1: 28, 2: 16, 3: 14, 4: 6, 5: 20})

    # Transcript Sheet
    ws_tr = wb.create_sheet("Chat Transcript")
    rt = _style_banner(
        ws_tr,
        "Rajasthan Administrative & Geographic Support — Chat Transcript",
        f"Session: {session_id}  |  Messages: {len(messages)}  |  Official Helpline: {support_phone}",
        col_count=6,
        accent=INDIGO,
    )
    _style_table_header(ws_tr, rt, ["#", "Time", "Sender", "Intent / Stage", "Message / AI Response", "Hierarchy Breadcrumbs"], bg=NAVY)
    tr_start = rt + 1
    for idx, m in enumerate(messages, start=1):
        ri = tr_start + idx - 1
        sender = "User" if m.get("sender") == "user" else "RajMaster AI"
        txt = _clean_text(m.get("text"), max_len=12000)
        line_cnt = max(2, txt.count("\n") + 1 + len(txt) // 70)
        ws_tr.row_dimensions[ri].height = min(max(24, line_cnt * 15), 260)

        crumbs = " -> ".join(m.get("breadcrumbs") or []) if isinstance(m.get("breadcrumbs"), list) else ""
        stage_parts = [p for p in [m.get("intent"), m.get("resolutionStage")] if p]
        stage_str = " | ".join(stage_parts)

        vals = [idx, _clean_text(m.get("timestamp")), sender, stage_str, txt, crumbs]
        bg = LIGHT_PEACH if sender == "User" else LIGHT_SLATE
        for ci, v in enumerate(vals, start=1):
            c = ws_tr.cell(row=ri, column=ci, value=v)
            c.border = THIN_BORDER
            c.fill = _fill(bg)
            c.font = _font(10, bold=(ci in (1, 3)))
            c.alignment = Alignment(horizontal="center" if ci in (1, 2, 3) else "left", vertical="top", wrap_text=True)
            if ci == 3:
                c.fill = _fill(AMBER_BG if sender == "User" else EMERALD_BG)
                c.font = _font(10, bold=True, color=AMBER_FG if sender == "User" else EMERALD_FG)

    ws_tr.freeze_panes = f"A{tr_start}"
    _auto_fit_columns(ws_tr, {1: 6, 2: 20, 3: 15, 4: 24, 5: 68, 6: 36})

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PUBLIC CHAT EXPORT: UNICODE PDF (.pdf) WITH DEVANAGARI SHAPING
# ---------------------------------------------------------------------------
def _find_font_files() -> Dict[str, Optional[str]]:
    win_fonts = r"C:\Windows\Fonts"
    candidates = {
        "latin": [
            os.path.join(win_fonts, "NotoSans-VariableFont_wdth,wght.ttf"),
            os.path.join(win_fonts, "segoeui.ttf"),
            os.path.join(win_fonts, "arial.ttf"),
        ],
        "latin_bold": [
            os.path.join(win_fonts, "segoeuib.ttf"),
            os.path.join(win_fonts, "arialbd.ttf"),
        ],
        "devanagari": [
            os.path.join(win_fonts, "NotoSansDevanagari-Regular.ttf"),
            os.path.join(win_fonts, "Nirmala.ttc"),
        ],
    }
    res: Dict[str, Optional[str]] = {}
    for k, paths in candidates.items():
        res[k] = next((p for p in paths if os.path.exists(p)), None)
    return res


def _strip_unsupported_emoji(text: str) -> str:
    """Replaces pictographic emoji with clean ASCII/Unicode tags so PDF fonts never render missing glyph boxes."""
    replacements = {
        "🏛️": "[Admin]", "🏛": "[Admin]",
        "📍": "[Loc]", "📮": "[PIN]",
        "🏡": "[Village]", "🏘️": "[GP]", "🏘": "[GP]",
        "🏙️": "[ULB]", "🏙": "[ULB]",
        "📞": "[Call]", "✨": "*", "🔌": "[MCP]",
        "📚": "[RAG]", "🌐": "[Web]", "🔍": "[Search]",
        "🧭": "[Hierarchy]", "ℹ️": "[Info]", "🙏": "",
        "👤": "[User]", "🛡️": "[Shield]",
    }
    for em, sub in replacements.items():
        text = text.replace(em, sub)
    # Strip remaining astral symbols (> U+FFFF) unsupported by Latin/Devanagari TTFs
    return "".join(ch if ord(ch) <= 0xFFFF else "" for ch in text)


class _ChatPDF(FPDF):
    def __init__(self, session_id: str, support_phone: str, main_font: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.session_id = session_id
        self.support_phone = support_phone
        self.main_font = main_font

    def header(self):
        self.set_fill_color(30, 41, 59)  # Navy
        self.rect(0, 0, 210, 20, "F")
        self.set_fill_color(234, 88, 12)  # Saffron stripe
        self.rect(0, 20, 210, 2.2, "F")

        self.set_xy(12, 4)
        self.set_text_color(255, 255, 255)
        self.set_font(self.main_font, "", 13)
        self.cell(140, 7, "RajMaster AI — Rajasthan Geographic Master Transcript", new_x="RIGHT", new_y="TOP")

        self.set_font(self.main_font, "", 8.5)
        self.set_text_color(254, 215, 170)
        self.set_xy(12, 12)
        self.cell(186, 5, f"Session: {self.session_id}  |  Helpline: {self.support_phone}  |  Exported: {datetime.now().strftime('%d %b %Y %I:%M %p')}")
        self.set_y(27)

    def footer(self):
        self.set_y(-12)
        self.set_font(self.main_font, "", 8)
        self.set_text_color(100, 116, 139)
        self.cell(0, 8, f"Rajasthan Administrative & Geographic Support System  •  Page {self.page_no()}/{{nb}}", align="C")


def build_chat_pdf(
    session_id: str,
    messages: List[Dict[str, Any]],
    language: str = "en",
    support_phone: str = "89988555525",
) -> bytes:
    fonts = _find_font_files()
    main_font = "BodyFont" if fonts["latin"] else "helvetica"

    pdf = _ChatPDF(session_id=session_id, support_phone=support_phone, main_font=main_font)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.alias_nb_pages()

    try:
        if fonts["latin"]:
            pdf.add_font("BodyFont", "", fonts["latin"])
        if fonts["devanagari"]:
            pdf.add_font("DevaFont", "", fonts["devanagari"])
            pdf.set_fallback_fonts(["DevaFont"])
        pdf.set_text_shaping(use_shaping_engine=True)
    except Exception:
        # Fallback gracefully if shaping engine cannot load a system font
        pdf.set_text_shaping(use_shaping_engine=False)

    pdf.add_page()

    # Summary strip box
    user_cnt = sum(1 for m in messages if m.get("sender") == "user")
    bot_cnt = len(messages) - user_cnt
    pdf.set_fill_color(255, 247, 237)
    pdf.set_draw_color(253, 186, 116)
    pdf.rect(12, 27, 186, 12, "DF")
    pdf.set_xy(15, 29.5)
    pdf.set_font(main_font, "", 9.5)
    pdf.set_text_color(154, 52, 18)
    pdf.cell(
        180,
        7,
        f"Conversation Summary   |   Messages: {len(messages)}   |   Questions: {user_cnt}   |   AI Replies: {bot_cnt}   |   Language: {language.upper()}",
    )
    pdf.set_y(44)

    for idx, m in enumerate(messages, start=1):
        sender_is_user = m.get("sender") == "user"
        ts = _strip_unsupported_emoji(str(m.get("timestamp") or ""))
        txt = _strip_unsupported_emoji(_clean_text(m.get("text"), max_len=8000)).strip()
        crumbs = m.get("breadcrumbs") or []
        intent_lbl = str(m.get("intent") or "").replace("_", " ").upper()

        if pdf.get_y() > 255:
            pdf.add_page()

        # Sender badge row
        if sender_is_user:
            pdf.set_fill_color(234, 88, 12)
            pdf.set_text_color(255, 255, 255)
            header_lbl = f"  #{idx}  CITIZEN / USER   ({ts})" if ts else f"  #{idx}  CITIZEN / USER"
        else:
            pdf.set_fill_color(30, 41, 59)
            pdf.set_text_color(255, 255, 255)
            meta_tag = f"  [{intent_lbl}]" if intent_lbl else ""
            header_lbl = f"  #{idx}  RAJMASTER AI ASSISTANT{meta_tag}   ({ts})" if ts else f"  #{idx}  RAJMASTER AI ASSISTANT{meta_tag}"

        pdf.set_font(main_font, "", 9)
        pdf.set_x(12)
        pdf.cell(186, 6.5, header_lbl, fill=True, new_x="LMARGIN", new_y="NEXT")

        # Breadcrumbs strip if present
        if crumbs and isinstance(crumbs, list):
            pdf.set_fill_color(241, 245, 249)
            pdf.set_text_color(71, 85, 105)
            pdf.set_font(main_font, "", 8)
            pdf.set_x(12)
            crumb_str = _strip_unsupported_emoji("  Hierarchy: " + " > ".join(str(c) for c in crumbs))
            pdf.multi_cell(186, 5, crumb_str, fill=True, new_x="LMARGIN", new_y="NEXT")

        # Message body
        pdf.set_fill_color(255, 251, 235) if sender_is_user else pdf.set_fill_color(255, 255, 255)
        pdf.set_draw_color(203, 213, 225)
        pdf.set_text_color(15, 23, 42)
        pdf.set_font(main_font, "", 9.5)
        pdf.set_x(12)
        pdf.multi_cell(186, 5.4, txt or "-", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3.5)

    out = pdf.output()
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin1")
