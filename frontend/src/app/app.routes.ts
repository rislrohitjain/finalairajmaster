import { Routes } from '@angular/router';
import { ChatComponent } from './components/chat/chat.component';
import { AdminLoginComponent } from './components/admin-login/admin-login.component';
import { AdminDashboardComponent } from './components/admin-dashboard/admin-dashboard.component';
import { VoiceAgentComponent } from './components/voice-agent/voice-agent.component';
import { authGuard } from './guards/auth.guard';

export const routes: Routes = [
  { path: '', component: ChatComponent },
  { path: 'voice', component: VoiceAgentComponent },
  { path: 'admin/login', component: AdminLoginComponent },
  { path: 'admin/dashboard', component: AdminDashboardComponent, canActivate: [authGuard] },
  { path: '**', redirectTo: '' }
];
