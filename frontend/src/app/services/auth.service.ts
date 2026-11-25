import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, tap } from 'rxjs';
import { environment } from '../../environments/environment';

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
  role: string;
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private apiUrl = environment.apiUrl;
  private tokenKey = 'rajmaster_admin_token';
  private userKey = 'rajmaster_admin_user';

  isLoggedInSignal = signal<boolean>(this.hasToken());
  currentUser = signal<string | null>(this.getStoredUser());

  constructor(private http: HttpClient) {}

  login(username: string, password: string): Observable<LoginResponse> {
    return this.http.post<LoginResponse>(`${this.apiUrl}/admin/login`, { username, password }).pipe(
      tap(res => {
        if (res.access_token) {
          localStorage.setItem(this.tokenKey, res.access_token);
          localStorage.setItem(this.userKey, res.username);
          this.isLoggedInSignal.set(true);
          this.currentUser.set(res.username);
        }
      })
    );
  }

  logout() {
    localStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.userKey);
    this.isLoggedInSignal.set(false);
    this.currentUser.set(null);
  }

  isTokenExpired(token: string | null): boolean {
    if (!token || token === 'null' || token === 'undefined') return true;
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return true;
      const base64Url = parts[1];
      const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      const jsonPayload = decodeURIComponent(
        atob(base64)
          .split('')
          .map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
          .join('')
      );
      const payload = JSON.parse(jsonPayload);
      if (!payload.exp) return false;
      return payload.exp * 1000 <= Date.now();
    } catch {
      return true;
    }
  }

  isLoggedIn(): boolean {
    const valid = this.hasToken();
    if (this.isLoggedInSignal() !== valid) {
      this.isLoggedInSignal.set(valid);
    }
    return valid;
  }

  hasToken(): boolean {
    const token = localStorage.getItem(this.tokenKey);
    if (!token || this.isTokenExpired(token)) {
      if (token) {
        localStorage.removeItem(this.tokenKey);
        localStorage.removeItem(this.userKey);
        this.currentUser.set(null);
      }
      return false;
    }
    return true;
  }

  getToken(): string | null {
    const token = localStorage.getItem(this.tokenKey);
    if (!token || this.isTokenExpired(token)) {
      this.logout();
      return null;
    }
    return token;
  }

  private getStoredUser(): string | null {
    return localStorage.getItem(this.userKey);
  }

  getAuthHeaders(): HttpHeaders {
    const token = this.getToken();
    return new HttpHeaders({
      'Authorization': `Bearer ${token}`
    });
  }
}
