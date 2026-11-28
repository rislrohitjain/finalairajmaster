import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule, ActivatedRoute } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-admin-login',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './admin-login.component.html'
})
export class AdminLoginComponent implements OnInit {
  username: string = '';
  password: string = '';
  errorMessage: string = '';
  sessionNotice: string = '';
  isLoading: boolean = false;

  constructor(
    public auth: AuthService,
    private router: Router,
    private route: ActivatedRoute
  ) {}

  onBrandClick(event?: Event): void {
    if (event) event.preventDefault();
    if (this.auth.isLoggedIn()) {
      this.router.navigate(['/admin/dashboard']);
    } else {
      this.router.navigate(['/']);
    }
  }

  ngOnInit(): void {
    this.route.queryParams.subscribe(params => {
      if (params['expired']) {
        this.sessionNotice = 'Your admin session expired. Please sign in again.';
        this.auth.logout();
      } else if (this.auth.isLoggedIn()) {
        this.router.navigate(['/admin/dashboard']);
      }
    });
  }

  fillDefaults(): void {
    // Hidden per security preference
  }

  onLogin(event?: Event): void {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (this.isLoading) return;

    if (this.auth.isLoggedIn()) {
      this.errorMessage = `Admin "${this.auth.currentUser() || 'active'}" is already logged in. Please log out first before signing in as another user.`;
      return;
    }

    const u = (this.username || '').trim();
    const p = (this.password || '').trim();

    if (!u || !p) {
      this.errorMessage = 'Please enter both username and password';
      return;
    }

    this.isLoading = true;
    this.errorMessage = '';
    this.sessionNotice = '';

    this.auth.login(u, p).subscribe({
      next: () => {
        this.isLoading = false;
        this.router.navigate(['/admin/dashboard']);
      },
      error: (err) => {
        this.isLoading = false;
        this.errorMessage = err.error?.detail || 'Invalid login credentials. Please check your username and password.';
      }
    });
  }
}
