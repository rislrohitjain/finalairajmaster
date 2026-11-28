import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, tap, of, catchError, throwError } from 'rxjs';
import { environment } from '../../environments/environment';

export interface UserProfile {
  id: number;
  username: string;
  name: string;
  phone?: string;
  email?: string;
  preferred_language: string;
  role: string;
  created_at: string;
}

export interface UserAuthResponse {
  access_token: string;
  token_type: string;
  user: UserProfile;
}

@Injectable({
  providedIn: 'root'
})
export class UserService {
  private apiUrl = `${environment.apiUrl}/user`;
  private tokenKey = 'rajmaster_user_token';
  private profileKey = 'rajmaster_user_profile';
  private guestNameKey = 'rajmaster_guest_name';

  currentUser = signal<UserProfile | null>(this.getStoredProfile());
  isLoggedIn = signal<boolean>(this.checkLoggedIn());
  guestName = signal<string>(this.getStoredGuestName());

  constructor(private http: HttpClient) {
    if (!this.isLoggedIn()) {
      this.currentUser.set(null);
    }
  }

  private isTokenValidJwt(token: string | null): boolean {
    if (!token || token === 'null' || token === 'undefined') return false;
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return false;
      const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
      const payload = JSON.parse(atob(base64));
      if (!payload.sub) return false;
      if (payload.exp && payload.exp * 1000 <= Date.now()) return false;
      return true;
    } catch {
      return false;
    }
  }

  private checkLoggedIn(): boolean {
    const token = localStorage.getItem(this.tokenKey);
    const profile = localStorage.getItem(this.profileKey);
    if (!token || !profile || !this.isTokenValidJwt(token)) {
      if (token || profile) {
        localStorage.removeItem(this.tokenKey);
        localStorage.removeItem(this.profileKey);
      }
      return false;
    }
    return true;
  }

  getStoredProfile(): UserProfile | null {
    try {
      const token = localStorage.getItem(this.tokenKey);
      if (!this.isTokenValidJwt(token)) return null;
      const data = localStorage.getItem(this.profileKey);
      return data ? JSON.parse(data) : null;
    } catch {
      return null;
    }
  }

  private getStoredGuestName(): string {
    try {
      return localStorage.getItem(this.guestNameKey) || '';
    } catch {
      return '';
    }
  }

  getStoredToken(): string | null {
    const token = localStorage.getItem(this.tokenKey);
    return this.isTokenValidJwt(token) ? token : null;
  }

  getAuthHeaders(): HttpHeaders {
    const token = this.getStoredToken();
    return token
      ? new HttpHeaders({ 'Authorization': `Bearer ${token}` })
      : new HttpHeaders();
  }

  register(data: { name: string; username: string; phone?: string; email?: string; password: string; preferred_language?: string }): Observable<UserAuthResponse> {
    if (this.isLoggedIn()) {
      const activeName = this.currentUser()?.username || 'current user';
      return throwError(() => ({
        status: 409,
        error: { detail: `User "${activeName}" is already logged in. Please sign out first before creating or logging into another account.` }
      }));
    }

    return this.http.post<UserAuthResponse>(`${this.apiUrl}/register`, data, { headers: this.getAuthHeaders() }).pipe(
      tap(res => {
        if (res && res.access_token && res.user) {
          this.setSession(res.access_token, res.user);
        }
      })
    );
  }

  login(username: string, password: string): Observable<UserAuthResponse> {
    if (this.isLoggedIn()) {
      const activeName = this.currentUser()?.username || 'current user';
      return throwError(() => ({
        status: 409,
        error: { detail: `User "${activeName}" is already logged in. Please sign out first before logging in another user.` }
      }));
    }

    return this.http.post<UserAuthResponse>(`${this.apiUrl}/login`, { username, password }, { headers: this.getAuthHeaders() }).pipe(
      tap(res => {
        if (res && res.access_token && res.user) {
          this.setSession(res.access_token, res.user);
        }
      })
    );
  }

  updateProfile(data: { name?: string; phone?: string; email?: string; preferred_language?: string }): Observable<UserProfile> {
    return this.http.put<UserProfile>(`${this.apiUrl}/profile`, data, { headers: this.getAuthHeaders() }).pipe(
      tap(updated => {
        if (updated) {
          this.setProfile(updated);
        }
      }),
      catchError(() => {
        const cur = this.currentUser();
        if (!cur) {
          return throwError(() => ({ status: 401, error: { detail: 'Please sign in first.' } }));
        }
        const updated: UserProfile = {
          ...cur,
          name: data.name !== undefined ? data.name : cur.name,
          phone: data.phone !== undefined ? data.phone : cur.phone,
          email: data.email !== undefined ? data.email : cur.email,
          preferred_language: data.preferred_language !== undefined ? data.preferred_language : cur.preferred_language
        };
        this.setProfile(updated);
        return of(updated);
      })
    );
  }

  setUserName(name: string): void {
    const clean = name.trim();
    if (!clean) return;
    if (this.isLoggedIn() && this.currentUser()) {
      this.updateProfile({ name: clean }).subscribe();
    } else {
      // Save casual greeting name without logging in or creating a fake session
      localStorage.setItem(this.guestNameKey, clean);
      this.guestName.set(clean);
    }
  }

  private setSession(token: string, user: UserProfile) {
    localStorage.setItem(this.tokenKey, token);
    localStorage.setItem(this.profileKey, JSON.stringify(user));
    this.currentUser.set(user);
    this.isLoggedIn.set(true);
  }

  private setProfile(user: UserProfile) {
    localStorage.setItem(this.profileKey, JSON.stringify(user));
    this.currentUser.set(user);
  }

  logout() {
    localStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.profileKey);
    this.currentUser.set(null);
    this.isLoggedIn.set(false);
  }
}
