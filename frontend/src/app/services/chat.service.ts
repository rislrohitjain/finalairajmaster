import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: Date;
  intent?: string;
  language?: string;
  nextQuestions?: string[];
  breadcrumbs?: string[];
  helplineCard?: boolean;
  supportPhone?: string;
  isStreaming?: boolean;
  viewMode?: 'preview' | 'raw';
  copied?: boolean;
}

export interface CapabilityData {
  title: string;
  greeting: string;
  support_phone: string;
  administrative_levels: Array<{
    level: number;
    name: string;
    authority: string;
    scope: string;
  }>;
  sample_prompts: string[];
}

export interface ExampleQuestion {
  id: number;
  category: string;
  question: string;
  tag: string;
}

export interface ExampleQuestionsResponse {
  total: number;
  categories: string[];
  questions: ExampleQuestion[];
}

@Injectable({
  providedIn: 'root'
})
export class ChatService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  getCapabilities(): Observable<CapabilityData> {
    return this.http.get<CapabilityData>(`${this.apiUrl}/capabilities`);
  }

  getExampleQuestions(category?: string): Observable<ExampleQuestionsResponse> {
    const url = category && category !== 'All'
      ? `${this.apiUrl}/example-questions?category=${encodeURIComponent(category)}`
      : `${this.apiUrl}/example-questions`;
    return this.http.get<ExampleQuestionsResponse>(url);
  }

  searchGeo(query: string): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/geo/search?q=${encodeURIComponent(query)}`);
  }

  sendMessage(sessionId: string, query: string, language: string = 'en'): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/chat`, {
      session_id: sessionId,
      query: query,
      language: language
    });
  }

  async streamMessage(
    sessionId: string,
    query: string,
    onToken: (token: string) => void,
    onComplete: (meta: any) => void,
    onError: (err: any) => void,
    language: string = 'en'
  ) {
    try {
      const response = await fetch(`${this.apiUrl}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          query: query,
          language: language
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('ReadableStream not supported.');
      }

      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.substring(6);
            try {
              const data = JSON.parse(jsonStr);
              if (data.token) {
                onToken(data.token);
              }
              if (data.done) {
                onComplete(data);
                return;
              }
            } catch (e) {
              console.error('Error parsing SSE data:', e, jsonStr);
            }
          }
        }
      }
    } catch (err) {
      onError(err);
    }
  }
}
