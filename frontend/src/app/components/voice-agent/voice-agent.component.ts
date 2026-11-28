import { Component, OnInit, OnDestroy, Output, EventEmitter, Input, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { VoiceService, VoiceState, VoiceLanguage } from '../../services/voice.service';
import { ChatService, PipelineStep } from '../../services/chat.service';

@Component({
  selector: 'app-voice-agent',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './voice-agent.component.html',
  styleUrls: ['./voice-agent.component.css']
})
export class VoiceAgentComponent implements OnInit, OnDestroy {
  @Input() isStandaloneRoute: boolean = false;
  @Output() close = new EventEmitter<void>();

  // State
  voiceState: VoiceState = 'idle';
  currentLanguage: VoiceLanguage = 'hinglish';
  activeVoiceName: string = '';
  audioLevel: number = 0;
  userTranscript: string = '';
  agentSpokenText: string = '';
  agentFullResponse: string = '';
  nextExpectedQuestions: string[] = [];
  pipelineSteps: PipelineStep[] = [];
  isResponseStreaming: boolean = false;
  showStepsPanel: boolean = true;
  lastLatencyMs: number | null = null;
  mcpUsed: boolean = false;
  mcpTool: string = '';

  // Controls
  isMicMuted: boolean = false;
  isSpeakerMuted: boolean = false;
  isContinuousMode: boolean = true;
  showTextInput: boolean = false;
  manualQueryInput: string = '';

  // Quick Suggestion Chips
  suggestedVoiceQuestions = [
    { label: '📍 Muhana Village Hierarchy', query: 'What is the administrative lineage of Muhana village?' },
    { label: '🏛️ Jaipur Division Districts', query: 'Jaipur Division mein kaun se districts aate hain?' },
    { label: '📮 Pincode 302029 Details', query: 'Details of pincode 302029' },
    { label: '🌾 Villages in Jodhpur', query: 'number of villages in Jodhpur' },
    { label: '🏢 Sanganer Tehsil Authority', query: 'Sanganer tehsil ke administrative details batao' },
    { label: '🏘️ Rajasthan Ke 10 Sambhag', query: 'Rajasthan ke 10 sambhag kaun se hain?' }
  ];

  private subscriptions: Subscription[] = [];
  private sessionId: string = 'jain-voice-' + Math.random().toString(36).substring(2, 9);
  private conversationHistory: Array<{ sender: 'user' | 'agent', text: string }> = [];

  constructor(
    public voiceService: VoiceService,
    private chatService: ChatService,
    private router: Router,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    if (this.router.url.includes('/voice')) {
      this.isStandaloneRoute = true;
    }
    this.currentLanguage = this.voiceService.getLanguage();
    this.activeVoiceName = this.voiceService.getActiveVoiceName();
    this.isMicMuted = this.voiceService.isMicMutedStatus();
    this.isSpeakerMuted = this.voiceService.isSpeakerMutedStatus();
    this.isContinuousMode = this.voiceService.isContinuousMode();

    // Listen to voice service state changes
    this.subscriptions.push(
      this.voiceService.state$.subscribe((state) => {
        this.voiceState = state;
        this.cdr.detectChanges();
      }),
      this.voiceService.transcript$.subscribe((text) => {
        if (text) {
          this.userTranscript = text;
        }
        this.cdr.detectChanges();
      }),
      this.voiceService.spokenText$.subscribe((text) => {
        this.agentSpokenText = text;
        this.cdr.detectChanges();
      }),
      this.voiceService.audioLevel$.subscribe((level) => {
        this.audioLevel = level;
        this.cdr.detectChanges();
      })
    );

    // Initial greeting in authentic Indian female voice
    setTimeout(() => {
      this.playInitialGreeting();
    }, 600);
  }

  ngOnDestroy(): void {
    this.voiceService.stopListening();
    this.voiceService.stopSpeaking();
    this.subscriptions.forEach(sub => sub.unsubscribe());
  }

  // --- Initial Voice Greeting ---
  private playInitialGreeting(): void {
    let greetingText = '';
    if (this.currentLanguage === 'hi') {
      greetingText = 'नमस्ते! मैं राजस्थान एडमिनिस्ट्रेटिव मास्टर AI शोकेस की वॉयस असिस्टेंट हूँ। आप राजस्थान के किसी भी संभाग, जिले, तहसील या गांव के बारे में पूछ सकते हैं।';
    } else if (this.currentLanguage === 'hinglish') {
      greetingText = 'Namaste! Main Rajasthan Administrative Master AI Showcase ki voice assistant hoon. Aap kisi bhi district, tehsil ya village ke baare mein pooch sakte hain.';
    } else {
      greetingText = 'Namaste! I am your voice assistant for the Rajasthan AI and LLM Architecture Showcase. Feel free to ask about any division, district, tehsil, or village.';
    }

    this.agentSpokenText = greetingText;
    this.voiceService.speak(greetingText, () => {
      // If continuous mode is enabled, start listening after greeting!
      if (this.isContinuousMode && !this.isMicMuted) {
        setTimeout(() => this.triggerListening(), 500);
      }
    });
  }

  // --- Language Switching ---
  public setLanguage(lang: VoiceLanguage): void {
    this.currentLanguage = lang;
    this.voiceService.setLanguage(lang);
    this.activeVoiceName = this.voiceService.getActiveVoiceName();
    
    // Announce language switch
    let msg = '';
    if (lang === 'hi') msg = 'हिन्दी भाषा का चयन किया गया है। अब मैं हिन्दी में उत्तर दूँगी।';
    else if (lang === 'hinglish') msg = 'Hinglish language selected. Ab main Hinglish mein baat karungi.';
    else msg = 'Indian English selected. I will now respond in Indian English.';

    this.voiceService.speak(msg, () => {
      if (this.isContinuousMode && !this.isMicMuted) {
        this.triggerListening();
      }
    });
  }

  // --- Conversational Flow ---
  public toggleOrbAction(): void {
    if (this.voiceState === 'speaking') {
      this.voiceService.stopSpeaking();
      if (!this.isMicMuted) {
        this.triggerListening();
      }
      return;
    }

    if (this.voiceState === 'listening') {
      this.voiceService.stopListening();
      return;
    }

    // Otherwise start listening
    this.triggerListening();
  }

  public triggerListening(): void {
    this.voiceService.startListening().then((finalQuery) => {
      if (finalQuery && finalQuery.trim()) {
        this.processUserQuery(finalQuery.trim());
      }
    }).catch((err) => {
      console.warn('Voice listening ended:', err);
    });
  }

  public processUserQuery(query: string): void {
    this.userTranscript = query;
    this.conversationHistory.push({ sender: 'user', text: query });
    this.pipelineSteps = [];
    this.agentSpokenText = '';
    this.agentFullResponse = '';
    this.isResponseStreaming = true;
    this.showStepsPanel = true;
    this.lastLatencyMs = null;
    this.mcpUsed = false;
    this.mcpTool = '';
    this.voiceService.setThinking();

    this.chatService.streamMessage(
      this.sessionId,
      query,
      (token: string) => {
        this.agentSpokenText += token.replace(/\*\*/g, '');
        this.cdr.detectChanges();
      },
      (meta: any) => {
        this.isResponseStreaming = false;
        this.agentFullResponse = this.agentSpokenText.trim();
        this.nextExpectedQuestions = meta.next_questions || [];
        this.lastLatencyMs = meta.latency_ms ?? null;
        this.mcpUsed = Boolean(meta.mcp_used);
        this.mcpTool = meta.mcp_tool || '';
        if (Array.isArray(meta.pipeline_steps) && meta.pipeline_steps.length > 0) {
          this.pipelineSteps = meta.pipeline_steps.map((s: any) => ({ ...s, status: 'done' }));
        } else {
          this.pipelineSteps = this.pipelineSteps.map(s => ({ ...s, status: 'done' }));
        }
        this.conversationHistory.push({ sender: 'agent', text: this.agentFullResponse });
        this.cdr.detectChanges();

        this.voiceService.speak(this.agentFullResponse, () => {
          if (this.isContinuousMode && !this.isMicMuted) {
            setTimeout(() => {
              this.triggerListening();
            }, 800);
          }
        });
      },
      () => {
        // Fallback to non-streaming POST /api/chat
        this.chatService.sendMessage(this.sessionId, query, this.currentLanguage).subscribe({
          next: (res) => {
            this.isResponseStreaming = false;
            this.agentFullResponse = res.response;
            this.agentSpokenText = (res.response || '').replace(/\*\*/g, '');
            this.nextExpectedQuestions = res.next_questions || [];
            this.lastLatencyMs = res.latency_ms ?? null;
            this.mcpUsed = Boolean(res.mcp_used);
            this.mcpTool = res.mcp_tool || '';
            if (Array.isArray(res.pipeline_steps)) {
              this.pipelineSteps = res.pipeline_steps.map((s: any) => ({ ...s, status: 'done' }));
            }
            this.conversationHistory.push({ sender: 'agent', text: res.response });
            this.cdr.detectChanges();

            this.voiceService.speak(res.response, () => {
              if (this.isContinuousMode && !this.isMicMuted) {
                setTimeout(() => {
                  this.triggerListening();
                }, 800);
              }
            });
          },
          error: () => {
            this.isResponseStreaming = false;
            const errorMsg = this.currentLanguage === 'hi'
              ? 'माफ़ कीजिए, डेटाबेस से संपर्क करने में समस्या हुई। कृपया पुनः प्रयास करें।'
              : 'Sorry, could not connect to the Rajasthan database. Please try again.';
            this.agentSpokenText = errorMsg;
            this.cdr.detectChanges();
            this.voiceService.speak(errorMsg);
          }
        });
      },
      this.currentLanguage,
      (step: PipelineStep) => {
        const steps = [...this.pipelineSteps];
        const idx = steps.findIndex(s => s.id === step.id);
        if (idx >= 0) {
          steps[idx] = step;
        } else {
          steps.push(step);
        }
        this.pipelineSteps = steps;
        this.cdr.detectChanges();
      }
    );
  }

  // --- Manual Text Fallback ---
  public submitManualQuery(): void {
    if (!this.manualQueryInput.trim()) return;
    const q = this.manualQueryInput.trim();
    this.manualQueryInput = '';
    this.showTextInput = false;
    this.processUserQuery(q);
  }

  // --- Controls ---
  public toggleMic(): void {
    this.isMicMuted = this.voiceService.toggleMuteMic();
  }

  public toggleSpeaker(): void {
    this.isSpeakerMuted = this.voiceService.toggleMuteSpeaker();
  }

  public toggleContinuous(): void {
    this.isContinuousMode = this.voiceService.toggleContinuousMode();
  }

  public exitVoiceMode(): void {
    this.voiceService.stopListening();
    this.voiceService.stopSpeaking();
    if (this.isStandaloneRoute || this.router.url.includes('/voice')) {
      this.router.navigate(['/']);
    } else {
      this.close.emit();
    }
  }

  // --- Helper getters ---
  public getStatusHeadline(): string {
    switch (this.voiceState) {
      case 'listening':
        return this.currentLanguage === 'hi' ? 'बोलिए, मैं सुन रही हूँ...' : 'Listening to your voice...';
      case 'thinking':
        return this.currentLanguage === 'hi' ? 'राजस्थान मास्टर रिकॉर्ड्स में खोज रही हूँ...' : 'Processing Rajasthan Master records...';
      case 'speaking':
        return this.currentLanguage === 'hi' ? 'उत्तर दे रही हूँ...' : 'Speaking in authentic Indian tone...';
      default:
        return this.currentLanguage === 'hi' ? 'बातचीत शुरू करने के लिए टैप करें' : 'Tap to speak with RajMaster Agent';
    }
  }
}
