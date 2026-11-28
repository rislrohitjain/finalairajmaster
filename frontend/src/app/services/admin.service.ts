import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

export interface LLMConfig {
  active_model: string;
  temperature: number;
  max_tokens: number;
  system_prompt: string;
  greeting_message: string;
  support_phone: string;
  enable_rag?: boolean;
  rag_top_k?: number;
  enable_web_search?: boolean;
  web_search_provider?: string;
  web_search_api_key?: string;
  web_search_max_results?: number;
  available_models: string[];
  ollama_base_url: string;
}

export interface ScraperRunItem {
  id: number;
  master_name: string;
  status: string;
  rows_fetched: number;
  rows_upserted: number;
  error_logs: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface GeoStats {
  divisions: number;
  districts: number;
  sub_divisions: number;
  tehsils_blocks: number;
  gram_panchayats: number;
  villages: number;
  urban_local_bodies: number;
  urban_wards: number;
  pincodes: number;
  total_entities: number;
}

export interface TimingStage {
  stage: string;
  component: string;
  tech: string;
  latency_ms: number;
  percentage: number;
  status: 'optimal' | 'moderate' | 'bottleneck';
  description: string;
}

export interface TimingBreakdown {
  python_ms: number;
  db_ms: number;
  llm_ms: number;
  postprocess_ms: number;
  total_ms: number;
  model: string;
  bottleneck_stage: string;
  stages: TimingStage[];
}

export interface ChatLogItem {
  id: number;
  session_id: string;
  user_query: string;
  detected_intent: string;
  ai_response: string;
  sql_lookup_trace: any;
  timing_breakdown?: TimingBreakdown;
  latency_ms: number;
  created_at: string;
}

export interface GeoRecord {
  id: number;
  level: string;
  name_en: string;
  name_hi: string;
  code: string;
  lgd_code?: number | null;
  parent_name: string;
  authority_details: string;
  pincode: string;
  extra_type: string;
}

export interface GeoRecordsResponse {
  level: string;
  total: number;
  records: GeoRecord[];
}

@Injectable({
  providedIn: 'root'
})
export class AdminService {
  private apiUrl = `${environment.apiUrl}/admin`;

  constructor(private http: HttpClient, private auth: AuthService) {}

  getLLMConfig(): Observable<LLMConfig> {
    return this.http.get<LLMConfig>(`${this.apiUrl}/llm-config`, {
      headers: this.auth.getAuthHeaders()
    });
  }

  updateLLMConfig(data: Partial<LLMConfig>): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}/llm-config`, data, {
      headers: this.auth.getAuthHeaders()
    });
  }

  triggerSync(masterName: string, limit: number = 100): Observable<any> {
    return this.http.post<any>(
      `${this.apiUrl}/sync-rajmaster`,
      { master_name: masterName, limit: limit },
      { headers: this.auth.getAuthHeaders() }
    );
  }

  getScraperRuns(limit: number = 20): Observable<ScraperRunItem[]> {
    return this.http.get<ScraperRunItem[]>(`${this.apiUrl}/scraper-runs?limit=${limit}`, {
      headers: this.auth.getAuthHeaders()
    });
  }

  getGeoStats(): Observable<GeoStats> {
    return this.http.get<GeoStats>(`${this.apiUrl}/geo-stats`, {
      headers: this.auth.getAuthHeaders()
    });
  }

  addGeoEntry(entry: {
    level: string;
    name_en: string;
    name_hi?: string;
    code?: string;
    parent_id?: number;
    lgd_code?: number;
    extra_details?: string;
  }): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/geo-entry`, entry, {
      headers: this.auth.getAuthHeaders()
    });
  }

  getChatLogs(limit: number = 30, intent?: string, search?: string): Observable<ChatLogItem[]> {
    let url = `${this.apiUrl}/chat-logs?limit=${limit}`;
    if (intent) url += `&intent=${encodeURIComponent(intent)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    return this.http.get<ChatLogItem[]>(url, {
      headers: this.auth.getAuthHeaders()
    });
  }

  getGeoRecords(level: string = 'district', search?: string, limit: number = 50, offset: number = 0): Observable<GeoRecordsResponse> {
    let url = `${this.apiUrl}/geo-records?level=${encodeURIComponent(level)}&limit=${limit}&offset=${offset}`;
    if (search && search.trim()) {
      url += `&search=${encodeURIComponent(search.trim())}`;
    }
    return this.http.get<GeoRecordsResponse>(url, {
      headers: this.auth.getAuthHeaders()
    });
  }

  updateGeoRecord(level: string, id: number, data: Partial<GeoRecord>): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}/geo-record/${encodeURIComponent(level)}/${id}`, data, {
      headers: this.auth.getAuthHeaders()
    });
  }

  deleteGeoRecord(level: string, id: number): Observable<any> {
    return this.http.delete<any>(`${this.apiUrl}/geo-record/${encodeURIComponent(level)}/${id}`, {
      headers: this.auth.getAuthHeaders()
    });
  }

  exportExcel(tab: string = 'all', level: string = 'district', search?: string, intent?: string): Observable<Blob> {
    let url = `${this.apiUrl}/export-excel?tab=${encodeURIComponent(tab)}&level=${encodeURIComponent(level)}`;
    if (search && search.trim()) url += `&search=${encodeURIComponent(search.trim())}`;
    if (intent && intent.trim()) url += `&intent=${encodeURIComponent(intent.trim())}`;
    return this.http.get(url, {
      headers: this.auth.getAuthHeaders(),
      responseType: 'blob'
    });
  }
}
