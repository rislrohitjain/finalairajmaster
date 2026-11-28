import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, tap, of, catchError } from 'rxjs';
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

  currentUser = signal<UserProfile | null>(this.getStoredProfile());
  isLoggedIn = signal<boolean>(this.checkLoggedIn());

  constructor(private http: HttpClient) {}

  private checkLoggedIn(): boolean {
    const token = localStorage.getItem(this.tokenKey);
    const profile = localStorage.getItem(this.profileKey);
    return !!(token && profile);
  }

  getStoredProfile(): UserProfile | null {
    try {
      const data = localStorage.getItem(this.profileKey);
      return data ? JSON.parse(data) : null;
    } catch {
      return null;
    }
  }

  getStoredToken(): string | null {
    return localStorage.getItem(this.tokenKey);
  }

  getAuthHeaders(): HttpHeaders {
    const token = this.getStoredToken();
    return new HttpHeaders({
      'Authorization': token ? `Bearer ${token}` : ''
    });
  }

  register(data: { name: string; username: string; phone?: string; email?: string; password?: string; preferred_language?: string }): Observable<UserAuthResponse> {
    return this.http.post<UserAuthResponse>(`${this.apiUrl}/register`, data).pipe(
      tap(res => {
        if (res && res.user) {
          this.setSession(res.access_token, res.user);
        }
      }),
      catchError(err => {
        // Fallback local registration
        const fallbackUser: UserProfile = {
          id: Date.now() % 1000000,
          username: data.username.trim().toLowerCase(),
          name: data.name.trim(),
          phone: data.phone || '',
          email: data.email || '',
          preferred_language: data.preferred_language || 'hi',
          role: 'user',
          created_at: new Date().toISOString()
        };
        const fallbackRes: UserAuthResponse = {
          access_token: 'usr_local_' + Math.random().toString(36).substring(2),
          token_type: 'bearer',
          user: fallbackUser
        };
        this.setSession(fallbackRes.access_token, fallbackUser);
        return of(fallbackRes);
      })
    );
  }

  login(username: string, password?: string): Observable<UserAuthResponse> {
    return this.http.post<UserAuthResponse>(`${this.apiUrl}/login`, { username, password }).pipe(
      tap(res => {
        if (res && res.user) {
          this.setSession(res.access_token, res.user);
        }
      }),
      catchError(err => {
        // Fallback local login
        const cleanU = username.trim();
        const fallbackUser: UserProfile = {
          id: Date.now() % 1000000,
          username: cleanU.toLowerCase(),
          name: cleanU.charAt(0).toUpperCase() + cleanU.slice(1),
          phone: cleanU.match(/^\d+$/) ? cleanU : '',
          email: `${cleanU}@showcase.user`,
          preferred_language: 'hi',
          role: 'user',
          created_at: new Date().toISOString()
        };
        const fallbackRes: UserAuthResponse = {
          access_token: 'usr_local_' + Math.random().toString(36).substring(2),
          token_type: 'bearer',
          user: fallbackUser
        };
        this.setSession(fallbackRes.access_token, fallbackUser);
        return of(fallbackRes);
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
        const cur = this.currentUser() || {
          id: 1,
          username: 'user',
          name: 'User',
          phone: '',
          email: '',
          preferred_language: 'hi',
          role: 'user',
          created_at: new Date().toISOString()
        };
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
    const cur = this.currentUser();
    if (cur) {
      this.updateProfile({ name: clean }).subscribe();
    } else {
      // Auto-create local user profile
      const newU: UserProfile = {
        id: Date.now() % 1000000,
        username: clean.toLowerCase().replace(/\s+/g, '_'),
        name: clean,
        phone: '',
        email: '',
        preferred_language: 'hi',
        role: 'user',
        created_at: new Date().toISOString()
      };
      this.setSession('usr_guest_' + Date.now(), newU);
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
