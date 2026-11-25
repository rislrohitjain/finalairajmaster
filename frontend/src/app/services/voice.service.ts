import { Injectable, NgZone } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'error';
export type VoiceLanguage = 'hi' | 'hinglish' | 'en';

@Injectable({
  providedIn: 'root'
})
export class VoiceService {
  private stateSubject = new BehaviorSubject<VoiceState>('idle');
  public state$: Observable<VoiceState> = this.stateSubject.asObservable();

  private transcriptSubject = new BehaviorSubject<string>('');
  public transcript$: Observable<string> = this.transcriptSubject.asObservable();

  private spokenTextSubject = new BehaviorSubject<string>('');
  public spokenText$: Observable<string> = this.spokenTextSubject.asObservable();

  private audioLevelSubject = new BehaviorSubject<number>(0);
  public audioLevel$: Observable<number> = this.audioLevelSubject.asObservable();

  private recognition: any = null;
  private currentLanguage: VoiceLanguage = 'hinglish';
  private availableVoices: SpeechSynthesisVoice[] = [];
  private selectedVoice: SpeechSynthesisVoice | null = null;
  private isMicMuted: boolean = false;
  private isSpeakerMuted: boolean = false;
  private continuousMode: boolean = true;
  private audioInterval: any = null;
  private activeUtterance: SpeechSynthesisUtterance | null = null;

  constructor(private zone: NgZone) {
    this.initSpeechRecognition();
    this.initSpeechSynthesis();
  }

  // --- Speech Recognition Setup ---
  private initSpeechRecognition(): void {
    if (typeof window === 'undefined') return;

    const SpeechRec = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRec) {
      console.warn('SpeechRecognition API not supported in this browser.');
      return;
    }

    try {
      this.recognition = new SpeechRec();
      this.recognition.continuous = false;
      this.recognition.interimResults = true;
      this.updateRecognitionLanguage();

      this.recognition.onstart = () => {
        this.zone.run(() => {
          this.stateSubject.next('listening');
          this.startAudioLevelSimulation();
        });
      };

      this.recognition.onresult = (event: any) => {
        let interim = '';
        let final = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            final += transcript;
          } else {
            interim += transcript;
          }
        }

        const currentText = (final || interim).trim();
        this.zone.run(() => {
          this.transcriptSubject.next(currentText);
        });
      };

      this.recognition.onerror = (event: any) => {
        console.warn('SpeechRecognition error:', event.error);
        this.zone.run(() => {
          this.stopAudioLevelSimulation();
          if (event.error !== 'no-speech') {
            this.stateSubject.next('idle');
          }
        });
      };

      this.recognition.onend = () => {
        this.zone.run(() => {
          this.stopAudioLevelSimulation();
          if (this.stateSubject.value === 'listening') {
            this.stateSubject.next('idle');
          }
        });
      };
    } catch (e) {
      console.error('Error initializing SpeechRecognition:', e);
    }
  }

  private updateRecognitionLanguage(): void {
    if (!this.recognition) return;
    if (this.currentLanguage === 'hi' || this.currentLanguage === 'hinglish') {
      this.recognition.lang = 'hi-IN';
    } else {
      this.recognition.lang = 'en-IN';
    }
  }

  // --- Speech Synthesis (Indian Female Voice) Setup ---
  private initSpeechSynthesis(): void {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;

    const loadVoices = () => {
      this.availableVoices = window.speechSynthesis.getVoices();
      this.resolveBestIndianFemaleVoice();
    };

    loadVoices();
    window.speechSynthesis.onvoiceschanged = () => {
      this.zone.run(() => loadVoices());
    };
  }

  /**
   * Resolves the highest quality Indian female voice available:
   * 1. Microsoft Swara (Hindi Natural Female)
   * 2. Microsoft Neerja (English India Natural Female)
   * 3. Microsoft Heera (Indian English / Hindi Female)
   * 4. Google हिन्दी (Female)
   * 5. Google English (India) (Female)
   * 6. Any hi-IN or en-IN female voice
   */
  private resolveBestIndianFemaleVoice(): void {
    if (!this.availableVoices || this.availableVoices.length === 0) return;

    const langPref = this.currentLanguage;

    // Search priority list
    if (langPref === 'hi' || langPref === 'hinglish') {
      // 1. Swara (Natural Hindi Female)
      const swara = this.availableVoices.find(v => 
        (v.lang.includes('hi') || v.lang.includes('IN')) && 
        v.name.toLowerCase().includes('swara')
      );
      if (swara) { this.selectedVoice = swara; return; }

      // 2. Google हिन्दी
      const googleHi = this.availableVoices.find(v => 
        v.lang.toLowerCase().replace('_', '-').includes('hi-in') && 
        v.name.toLowerCase().includes('google')
      );
      if (googleHi) { this.selectedVoice = googleHi; return; }

      // 3. Any hi-IN voice
      const anyHi = this.availableVoices.find(v => 
        v.lang.toLowerCase().replace('_', '-').startsWith('hi')
      );
      if (anyHi) { this.selectedVoice = anyHi; return; }
    }

    // 4. Neerja (English India Natural Female)
    const neerja = this.availableVoices.find(v => 
      v.lang.toLowerCase().replace('_', '-').includes('en-in') && 
      v.name.toLowerCase().includes('neerja')
    );
    if (neerja) { this.selectedVoice = neerja; return; }

    // 5. Heera
    const heera = this.availableVoices.find(v => 
      v.name.toLowerCase().includes('heera')
    );
    if (heera) { this.selectedVoice = heera; return; }

    // 6. Google English (India)
    const googleEnIn = this.availableVoices.find(v => 
      v.lang.toLowerCase().replace('_', '-').includes('en-in')
    );
    if (googleEnIn) { this.selectedVoice = googleEnIn; return; }

    // 7. Any Indian Voice (*-IN)
    const anyIn = this.availableVoices.find(v => 
      v.lang.toLowerCase().includes('in')
    );
    if (anyIn) { this.selectedVoice = anyIn; return; }

    // 8. Fallback to first available voice
    this.selectedVoice = this.availableVoices[0] || null;
  }

  // --- Public Control Methods ---

  public setLanguage(lang: VoiceLanguage): void {
    this.currentLanguage = lang;
    this.updateRecognitionLanguage();
    this.resolveBestIndianFemaleVoice();
  }

  public getLanguage(): VoiceLanguage {
    return this.currentLanguage;
  }

  public getActiveVoiceName(): string {
    if (this.selectedVoice) {
      return this.selectedVoice.name;
    }
    return this.currentLanguage === 'hi' 
      ? 'Indian Female (Swara/हिन्दी)' 
      : 'Indian Female (Neerja/English-IN)';
  }

  public startListening(): Promise<string> {
    return new Promise((resolve, reject) => {
      if (this.isMicMuted) {
        this.stateSubject.next('idle');
        return resolve('');
      }

      this.stopSpeaking();
      this.transcriptSubject.next('');

      if (!this.recognition) {
        console.warn('Speech recognition not available.');
        this.stateSubject.next('idle');
        return resolve('');
      }

      let lastCapturedText = '';
      let resolved = false;

      const finishWith = (result: string) => {
        if (resolved) return;
        resolved = true;
        this.stopAudioLevelSimulation();
        const trimmed = (result || lastCapturedText).trim();
        if (trimmed) {
          this.stateSubject.next('thinking');
          resolve(trimmed);
        } else {
          this.stateSubject.next('idle');
          resolve('');
        }
      };

      this.recognition.onresult = (event: any) => {
        let final = '';
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const t = event.results[i][0].transcript;
          if (event.results[i].isFinal) final += t;
          else interim += t;
        }
        const text = (final || interim).trim();
        if (text) {
          lastCapturedText = text;
        }
        this.zone.run(() => {
          this.transcriptSubject.next(text);
          if (final) {
            finishWith(final);
          }
        });
      };

      this.recognition.onerror = (err: any) => {
        this.zone.run(() => {
          this.stopAudioLevelSimulation();
          if (err.error === 'no-speech' || err.error === 'aborted') {
            finishWith(lastCapturedText);
          } else {
            this.stateSubject.next('idle');
            if (!resolved) {
              resolved = true;
              resolve(lastCapturedText);
            }
          }
        });
      };

      this.recognition.onend = () => {
        this.zone.run(() => {
          finishWith(lastCapturedText);
        });
      };

      try {
        this.recognition.start();
        this.stateSubject.next('listening');
        this.startAudioLevelSimulation();
      } catch (e) {
        // Recognition might already be running
        this.stateSubject.next('listening');
        this.startAudioLevelSimulation();
      }
    });
  }

  public stopListening(): void {
    if (this.recognition) {
      try {
        this.recognition.stop();
      } catch (e) {}
    }
    this.stopAudioLevelSimulation();
    this.stateSubject.next('idle');
  }

  public setThinking(): void {
    this.stateSubject.next('thinking');
  }

  /**
   * Speaks text using authentic Indian female vocal tone (Swara/Neerja/Google).
   * Automatically sanitizes markdown, arrows, emojis, and bullet points.
   */
  public speak(text: string, onComplete?: () => void): void {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      if (onComplete) onComplete();
      return;
    }

    this.stopSpeaking();

    if (this.isSpeakerMuted) {
      this.stateSubject.next('idle');
      if (onComplete) onComplete();
      return;
    }

    const cleanText = this.sanitizeForSpeech(text, this.currentLanguage);
    if (!cleanText.trim()) {
      this.stateSubject.next('idle');
      if (onComplete) onComplete();
      return;
    }

    this.zone.run(() => {
      this.spokenTextSubject.next(cleanText);
      this.stateSubject.next('speaking');
      this.startAudioLevelSimulation();
    });

    const utterance = new SpeechSynthesisUtterance(cleanText);
    this.activeUtterance = utterance;

    // Apply resolved Indian female voice
    if (this.selectedVoice) {
      utterance.voice = this.selectedVoice;
    }

    // Set locale
    if (this.currentLanguage === 'hi' || this.currentLanguage === 'hinglish') {
      utterance.lang = 'hi-IN';
    } else {
      utterance.lang = 'en-IN';
    }

    // Real Indian female vocal adjustments: pitch: ~1.1, rate: ~0.98
    utterance.pitch = 1.08;
    utterance.rate = 0.98;

    let finished = false;
    const finishSpeech = () => {
      if (finished) return;
      finished = true;
      if (speechWatchdog) clearTimeout(speechWatchdog);
      this.zone.run(() => {
        this.stopAudioLevelSimulation();
        this.stateSubject.next('idle');
        this.activeUtterance = null;
        if (onComplete) onComplete();
      });
    };

    utterance.onend = finishSpeech;
    utterance.onerror = (e) => {
      console.warn('Speech synthesis utterance error:', e);
      finishSpeech();
    };

    // Chrome audio engine workaround: resume if paused and set safety watchdog
    try {
      if (window.speechSynthesis.paused) {
        window.speechSynthesis.resume();
      }
      window.speechSynthesis.speak(utterance);
    } catch (e) {
      console.warn('window.speechSynthesis.speak exception:', e);
      finishSpeech();
      return;
    }

    // Safety watchdog: estimated duration based on text length (approx 15 chars/sec) + 4s buffer
    const maxDurationMs = Math.max(5000, Math.min(30000, (cleanText.length / 15) * 1000 + 4000));
    const speechWatchdog = setTimeout(() => {
      if (!finished && this.stateSubject.value === 'speaking') {
        console.warn('SpeechSynthesis watchdog triggered.');
        finishSpeech();
      }
    }, maxDurationMs);
  }

  public stopSpeaking(): void {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    this.activeUtterance = null;
    this.stopAudioLevelSimulation();
    if (this.stateSubject.value === 'speaking') {
      this.stateSubject.next('idle');
    }
  }

  public toggleMuteMic(): boolean {
    this.isMicMuted = !this.isMicMuted;
    if (this.isMicMuted && this.stateSubject.value === 'listening') {
      this.stopListening();
    }
    return this.isMicMuted;
  }

  public toggleMuteSpeaker(): boolean {
    this.isSpeakerMuted = !this.isSpeakerMuted;
    if (this.isSpeakerMuted && this.stateSubject.value === 'speaking') {
      this.stopSpeaking();
    }
    return this.isSpeakerMuted;
  }

  public isMicMutedStatus(): boolean {
    return this.isMicMuted;
  }

  public isSpeakerMutedStatus(): boolean {
    return this.isSpeakerMuted;
  }

  public toggleContinuousMode(): boolean {
    this.continuousMode = !this.continuousMode;
    return this.continuousMode;
  }

  public isContinuousMode(): boolean {
    return this.continuousMode;
  }

  // --- Audio Simulation for Jain Live Visualizer Orb ---
  private startAudioLevelSimulation(): void {
    this.stopAudioLevelSimulation();
    this.audioInterval = setInterval(() => {
      // Generate pulsating organic audio level between 0.3 and 1.0
      const level = 0.35 + Math.random() * 0.65;
      this.zone.run(() => {
        this.audioLevelSubject.next(level);
      });
    }, 120);
  }

  private stopAudioLevelSimulation(): void {
    if (this.audioInterval) {
      clearInterval(this.audioInterval);
      this.audioInterval = null;
    }
    this.audioLevelSubject.next(0);
  }

  /**
   * Sanitizes rich markdown, chevrons, headers, and bullet points into
   * smooth, natural spoken sentences suited for an Indian vocal delivery.
   */
  public sanitizeForSpeech(raw: string, lang: VoiceLanguage): string {
    if (!raw) return '';

    let text = raw;

    // 1. Remove markdown code blocks and HTML tags
    text = text.replace(/```[\s\S]*?```/g, '');
    text = text.replace(/<[^>]*>/g, '');

    // 2. Remove markdown bold/italics markers
    text = text.replace(/\*\*/g, '');
    text = text.replace(/[*_~`]/g, '');

    // 3. Clean up arrows into natural conversational Indian words
    if (lang === 'hi') {
      text = text.replace(/[➔➜➝→]/g, ' से होकर ');
    } else if (lang === 'hinglish') {
      text = text.replace(/[➔➜➝→]/g, ' se hokar ');
    } else {
      text = text.replace(/[➔➜➝→]/g, ' leading to ');
    }

    // 4. Remove emojis
    text = text.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '');

    // 5. Clean up headers and bullet markers
    text = text.replace(/^#+\s+/gm, '');
    text = text.replace(/^[•\-\*]\s+/gm, '');

    // 6. Remove Next Expected Questions block from spoken audio
    const nqIdx = text.indexOf('Next Expected Questions');
    if (nqIdx !== -1) {
      text = text.substring(0, nqIdx);
    }
    const hiNqIdx = text.indexOf('अगले संभावित प्रश्न');
    if (hiNqIdx !== -1) {
      text = text.substring(0, hiNqIdx);
    }

    // 7. Clean up multiple whitespaces and newlines
    text = text.replace(/\n+/g, '. ');
    text = text.replace(/\s+/g, ' ').trim();

    return text;
  }
}
