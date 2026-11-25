import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { AdminService, LLMConfig, ScraperRunItem, GeoStats, ChatLogItem, GeoRecord } from '../../services/admin.service';
import { AuthService } from '../../services/auth.service';
import { ChatService } from '../../services/chat.service';

@Component({
  selector: 'app-admin-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './admin-dashboard.component.html'
})
export class AdminDashboardComponent implements OnInit {
  activeTab: 'llm' | 'scraper' | 'database' | 'logs' = 'llm';

  // LLM State
  llmConfig: LLMConfig = {
    active_model: 'llama3.2:3b',
    temperature: 0.2,
    max_tokens: 1024,
    system_prompt: '',
    greeting_message: '',
    support_phone: '89988555525',
    enable_rag: true,
    rag_top_k: 5,
    enable_web_search: true,
    web_search_provider: 'duckduckgo',
    web_search_api_key: '',
    web_search_max_results: 4,
    available_models: [],
    ollama_base_url: 'http://localhost:11434'
  };
  llmSaveStatus: string = '';
  testPromptInput: string = 'What is the administrative lineage of Muhana village?';
  testPromptResult: string = '';
  isTestingPrompt: boolean = false;

  // Scraper State
  scraperRuns: ScraperRunItem[] = [];
  syncLimit: number = 200;
  isSyncing: boolean = false;
  syncNotice: string = '';
  availableMasters = [
    { name: 'DIVISION RAJASTHAN', label: 'Divisions (10)' },
    { name: 'DISTRICT RAJASTHAN', label: 'Districts & Zila Parishads (50)' },
    { name: 'SUB-DIVISION', label: 'Sub-Divisions (SDM)' },
    { name: 'TEHSIL RAJASTHAN', label: 'Tehsils' },
    { name: 'BLOCK RAJASTHAN', label: 'Panchayat Samitis (Blocks)' },
    { name: 'GRAM PANCHAYAT RAJASTHAN', label: 'Gram Panchayats' },
    { name: 'URBAN LOCAL BODY(CITY) RAJASTHAN', label: 'ULBs (Nagar Nigam/Parishad/Palika)' },
    { name: 'WARD RAJASTHAN', label: 'Urban Wards' },
    { name: 'VILLAGE RAJASTHAN', label: 'Revenue Villages & Patwar' }
  ];

  // Database Stats & Entry
  stats: GeoStats | null = null;
  newEntry = {
    level: 'village',
    name_en: '',
    name_hi: '',
    code: '',
    parent_id: undefined as number | undefined,
    lgd_code: undefined as number | undefined,
    extra_details: ''
  };
  entrySuccessNotice: string = '';

  // Geo Records Explorer & Edit State
  selectedBoxLevel: string = 'district';
  recordsList: GeoRecord[] = [];
  recordsTotal: number = 0;
  isLoadingRecords: boolean = false;
  recordSearchTerm: string = '';
  recordsLimit: number = 50;
  recordsOffset: number = 0;
  recordsNotice: string = '';

  // Editing Record Modal State
  editingRecord: GeoRecord | null = null;
  isSavingEdit: boolean = false;
  editModalNotice: string = '';

  // Chat Logs
  chatLogs: ChatLogItem[] = [];
  logSearchTerm: string = '';
  logIntentFilter: string = '';

  constructor(
    public adminService: AdminService,
    public auth: AuthService,
    private chatService: ChatService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.loadLLMConfig();
    this.loadStats();
    this.loadScraperRuns();
    this.loadLogs();
    this.loadRecords();
  }

  // --- LLM Methods ---
  loadLLMConfig(): void {
    this.adminService.getLLMConfig().subscribe({
      next: (cfg) => {
        this.llmConfig = cfg;
      },
      error: (err) => console.error('Failed to load LLM config:', err)
    });
  }

  saveLLMConfig(): void {
    this.llmSaveStatus = 'Saving...';
    this.adminService.updateLLMConfig(this.llmConfig).subscribe({
      next: () => {
        this.llmSaveStatus = '✓ Configuration saved successfully!';
        setTimeout(() => (this.llmSaveStatus = ''), 3500);
      },
      error: (err) => {
        this.llmSaveStatus = 'Error saving config: ' + (err.error?.detail || err.message);
      }
    });
  }

  runTestPrompt(): void {
    if (!this.testPromptInput.trim()) return;
    this.isTestingPrompt = true;
    this.testPromptResult = '';

    this.chatService.sendMessage('admin-test-' + Date.now(), this.testPromptInput).subscribe({
      next: (res) => {
        this.isTestingPrompt = false;
        this.testPromptResult = res.response;
      },
      error: (err) => {
        this.isTestingPrompt = false;
        this.testPromptResult = 'Test error: ' + (err.message || 'Unknown error');
      }
    });
  }

  // --- Scraper Methods ---
  loadScraperRuns(): void {
    this.adminService.getScraperRuns(25).subscribe({
      next: (runs) => (this.scraperRuns = runs),
      error: (err) => console.error('Failed to load scraper runs:', err)
    });
  }

  triggerSync(masterName: string): void {
    this.isSyncing = true;
    this.syncNotice = `Initiated sync for '${masterName}'...`;

    this.adminService.triggerSync(masterName, this.syncLimit).subscribe({
      next: (res) => {
        this.syncNotice = `Sync for '${masterName}' queued! Refreshing status...`;
        setTimeout(() => {
          this.loadScraperRuns();
          this.loadStats();
          this.isSyncing = false;
        }, 3000);
      },
      error: (err) => {
        this.syncNotice = 'Sync failed: ' + (err.error?.detail || err.message);
        this.isSyncing = false;
      }
    });
  }

  // --- Database Methods ---
  loadStats(): void {
    this.adminService.getGeoStats().subscribe({
      next: (stats) => (this.stats = stats),
      error: (err) => console.error('Failed to load geo stats:', err)
    });
  }

  // --- Geo Record Listing & Editing Methods (Box Click & Edit) ---
  selectBox(level: string): void {
    this.selectedBoxLevel = level;
    this.recordSearchTerm = '';
    this.recordsOffset = 0;
    this.loadRecords();
  }

  loadRecords(): void {
    this.isLoadingRecords = true;
    this.recordsNotice = '';
    this.adminService.getGeoRecords(
      this.selectedBoxLevel,
      this.recordSearchTerm,
      this.recordsLimit,
      this.recordsOffset
    ).subscribe({
      next: (res) => {
        this.recordsList = res.records;
        this.recordsTotal = res.total;
        this.isLoadingRecords = false;
      },
      error: (err) => {
        this.isLoadingRecords = false;
        console.error('Failed to load geo records:', err);
        this.recordsNotice = 'Error loading records: ' + (err.error?.detail || err.message);
      }
    });
  }

  onRecordSearch(): void {
    this.recordsOffset = 0;
    this.loadRecords();
  }

  clearRecordSearch(): void {
    this.recordSearchTerm = '';
    this.recordsOffset = 0;
    this.loadRecords();
  }

  openEditModal(record: GeoRecord): void {
    this.editingRecord = { ...record };
    this.editModalNotice = '';
  }

  closeEditModal(): void {
    this.editingRecord = null;
    this.editModalNotice = '';
    this.isSavingEdit = false;
  }

  saveEditRecord(): void {
    if (!this.editingRecord) return;
    this.isSavingEdit = true;
    this.editModalNotice = 'Saving changes to database...';

    this.adminService.updateGeoRecord(
      this.editingRecord.level,
      this.editingRecord.id,
      this.editingRecord
    ).subscribe({
      next: (res) => {
        this.isSavingEdit = false;
        this.editModalNotice = '✓ Successfully updated record in database!';
        this.loadRecords();
        this.loadStats();
        setTimeout(() => {
          this.closeEditModal();
        }, 1100);
      },
      error: (err) => {
        this.isSavingEdit = false;
        this.editModalNotice = 'Error saving record: ' + (err.error?.detail || err.message);
      }
    });
  }

  deleteRecord(record: GeoRecord): void {
    const confirmDelete = confirm(`Are you sure you want to permanently delete '${record.name_en}' from ${record.level}?`);
    if (!confirmDelete) return;

    this.adminService.deleteGeoRecord(record.level, record.id).subscribe({
      next: () => {
        this.recordsNotice = `✓ Successfully deleted '${record.name_en}'!`;
        this.loadRecords();
        this.loadStats();
        setTimeout(() => (this.recordsNotice = ''), 4000);
      },
      error: (err) => {
        alert('Error deleting record: ' + (err.error?.detail || err.message));
      }
    });
  }

  getLevelBadge(level: string): { name: string, icon: string, bg: string } {
    switch (level) {
      case 'division': return { name: 'Divisions', icon: '🏛️', bg: 'bg-purple-100 text-purple-800' };
      case 'district': return { name: 'Districts', icon: '📍', bg: 'bg-blue-100 text-blue-800' };
      case 'sub_division': return { name: 'Sub-Divisions', icon: '⚖️', bg: 'bg-indigo-100 text-indigo-800' };
      case 'tehsil_block': return { name: 'Tehsils / Blocks', icon: '🏢', bg: 'bg-amber-100 text-amber-800' };
      case 'gram_panchayat': return { name: 'Gram Panchayats', icon: '🏡', bg: 'bg-emerald-100 text-emerald-800' };
      case 'village': return { name: 'Revenue Villages', icon: '🌾', bg: 'bg-teal-100 text-teal-800' };
      case 'ulb': return { name: 'Urban Bodies (ULB)', icon: '🏙️', bg: 'bg-sky-100 text-sky-800' };
      case 'urban_ward': return { name: 'Urban Wards', icon: '🏘️', bg: 'bg-cyan-100 text-cyan-800' };
      case 'pincode': return { name: 'Pincodes', icon: '📮', bg: 'bg-orange-100 text-orange-800' };
      default: return { name: level, icon: '📌', bg: 'bg-slate-100 text-slate-800' };
    }
  }

  submitGeoEntry(): void {
    if (!this.newEntry.name_en) return;

    this.adminService.addGeoEntry(this.newEntry).subscribe({
      next: (res) => {
        this.entrySuccessNotice = `✓ Added ${this.newEntry.name_en} to ${this.newEntry.level}!`;
        this.newEntry = {
          level: 'village',
          name_en: '',
          name_hi: '',
          code: '',
          parent_id: undefined,
          lgd_code: undefined,
          extra_details: ''
        };
        this.loadStats();
        setTimeout(() => (this.entrySuccessNotice = ''), 4000);
      },
      error: (err) => {
        alert('Error adding entry: ' + (err.error?.detail || err.message));
      }
    });
  }

  // --- Chat Logs Methods ---
  loadLogs(): void {
    this.adminService.getChatLogs(40, this.logIntentFilter || undefined, this.logSearchTerm || undefined).subscribe({
      next: (logs) => (this.chatLogs = logs),
      error: (err) => console.error('Failed to load chat logs:', err)
    });
  }

  logout(): void {
    this.auth.logout();
    this.router.navigate(['/']);
  }
}
