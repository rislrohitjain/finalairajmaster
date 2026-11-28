import { Component, OnInit, OnDestroy, ElementRef, ViewChild, AfterViewChecked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ChatService, ChatMessage, CapabilityData, ExampleQuestion } from '../../services/chat.service';
import { AuthService } from '../../services/auth.service';
import { UserService, UserProfile } from '../../services/user.service';
import { VoiceAgentComponent } from '../voice-agent/voice-agent.component';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, VoiceAgentComponent],
  templateUrl: './chat.component.html',
  styleUrls: ['./chat.component.css']
})
export class ChatComponent implements OnInit, OnDestroy, AfterViewChecked {
  @ViewChild('scrollContainer') private scrollContainer!: ElementRef;

  sessionId: string = 'session-' + Math.random().toString(36).substring(2, 9);
  messages: ChatMessage[] = [];
  inputQuery: string = '';
  isStreaming: boolean = false;
  isSidebarOpen: boolean = false;
  capabilities: CapabilityData | null = null;
  mcpStatus: any = null;
  supportPhone: string = '89988555525';
  readonly resumeUrl: string = 'https://rohitjain-resume.vercel.app/';
  quickChips: string[] = [
    'Tell me about Muhana village administrative hierarchy',
    'Which division does Balotra district belong to?',
    'Details of pincode 302029',
    'Show database stats via MCP',
    'Who heads Sanganer tehsil and panchayat samiti?',
    'List all 10 divisions of Rajasthan',
    'What urban local body covers Malviya Nagar, Jaipur?'
  ];

  // Language Selection ('en' | 'hi' | 'hinglish')
  selectedLanguage: 'en' | 'hi' | 'hinglish' = 'en';

  setLanguage(lang: 'en' | 'hi' | 'hinglish'): void {
    this.selectedLanguage = lang;
  }

  // Jain Live Voice Agent Full Screen State
  isVoiceAgentOpen: boolean = false;

  openVoiceAgent(): void {
    this.isVoiceAgentOpen = true;
  }

  closeVoiceAgent(): void {
    this.isVoiceAgentOpen = false;
  }

  // Project Guide & Uses Modal State
  isAboutModalOpen: boolean = false;
  aboutLangTab: 'en' | 'hi' = 'en';

  openAboutModal(): void {
    this.isAboutModalOpen = true;
  }

  closeAboutModal(): void {
    this.isAboutModalOpen = false;
  }

  setAboutLangTab(lang: 'en' | 'hi'): void {
    this.aboutLangTab = lang;
  }

  // Text Chat Flow Modal State
  isTextFlowModalOpen: boolean = false;
  textFlowLangTab: 'en' | 'hi' = 'en';

  openTextFlowModal(): void {
    this.isTextFlowModalOpen = true;
    this.textFlowLangTab = this.selectedLanguage === 'hi' ? 'hi' : 'en';
  }

  closeTextFlowModal(): void {
    this.isTextFlowModalOpen = false;
  }

  setTextFlowLangTab(lang: 'en' | 'hi'): void {
    this.textFlowLangTab = lang;
  }

  // Audio / Voice Flow Modal State
  isAudioFlowModalOpen: boolean = false;
  audioFlowLangTab: 'en' | 'hi' = 'en';

  openAudioFlowModal(): void {
    this.isAudioFlowModalOpen = true;
    this.audioFlowLangTab = this.selectedLanguage === 'hi' ? 'hi' : 'en';
  }

  closeAudioFlowModal(): void {
    this.isAudioFlowModalOpen = false;
  }

  setAudioFlowLangTab(lang: 'en' | 'hi'): void {
    this.audioFlowLangTab = lang;
  }

  // 100+ Questions Modal State
  isQuestionsModalOpen: boolean = false;
  selectedCategory: string = 'All';
  questionSearchTerm: string = '';
  questionCategories: string[] = [
    'All',
    'Divisions & Districts',
    'Tehsils & Blocks',
    'Villages & Panchayats',
    'Urban Bodies & Wards',
    'Pincodes & Postal',
    'Officials & Governance',
    'Hindi / हिंदी प्रश्न',
    'Out-of-Scope Guardrails'
  ];

  // Curated 101 Example Questions
  allQuestions: ExampleQuestion[] = [
    // 1. Divisions & Districts (15)
    { id: 1, category: "Divisions & Districts", question: "What are the 10 administrative divisions of Rajasthan?", tag: "State / Division" },
    { id: 2, category: "Divisions & Districts", question: "Which division does Balotra district belong to?", tag: "District Mapping" },
    { id: 3, category: "Divisions & Districts", question: "What is the administrative hierarchy of Jaipur district?", tag: "District Lineage" },
    { id: 4, category: "Divisions & Districts", question: "Which division does Didwana-Kuchaman belong to?", tag: "New District" },
    { id: 5, category: "Divisions & Districts", question: "How many districts are in Jodhpur division?", tag: "Division Count" },
    { id: 6, category: "Divisions & Districts", question: "Details of Kotputli-Behror district and its division.", tag: "New District" },
    { id: 7, category: "Divisions & Districts", question: "List all districts under Kota division.", tag: "Division Roster" },
    { id: 8, category: "Divisions & Districts", question: "Which division does Anupgarh district come under?", tag: "District Mapping" },
    { id: 9, category: "Divisions & Districts", question: "What division administers Beawar district?", tag: "District Mapping" },
    { id: 10, category: "Divisions & Districts", question: "Details of Phalodi district collectorate and division.", tag: "Collectorate" },
    { id: 11, category: "Divisions & Districts", question: "Which division does Khairthal-Tijara district belong to?", tag: "District Mapping" },
    { id: 12, category: "Divisions & Districts", question: "List all districts under Udaipur division.", tag: "Division Roster" },
    { id: 13, category: "Divisions & Districts", question: "What division does Dudu district fall under?", tag: "Smallest District" },
    { id: 14, category: "Divisions & Districts", question: "Who is the divisional commissioner of Ajmer division?", tag: "Commissionerate" },
    { id: 15, category: "Divisions & Districts", question: "Which division does Shahpura district belong to?", tag: "District Mapping" },

    // 2. Tehsils & Blocks (15)
    { id: 16, category: "Tehsils & Blocks", question: "Administrative lineage of Sanganer tehsil.", tag: "Tehsil Lineage" },
    { id: 17, category: "Tehsils & Blocks", question: "Who heads Sanganer tehsil and panchayat samiti?", tag: "Tehsildar & BDO" },
    { id: 18, category: "Tehsils & Blocks", question: "What is the sub-division and district of Amber tehsil?", tag: "Sub-Division" },
    { id: 19, category: "Tehsils & Blocks", question: "Details of Bassi tehsil and block.", tag: "Tehsil Details" },
    { id: 20, category: "Tehsils & Blocks", question: "What sub-division does Chaksu tehsil belong to?", tag: "Sub-Division" },
    { id: 21, category: "Tehsils & Blocks", question: "Who is the Tehsildar and BDO for Jamwa Ramgarh?", tag: "Authority" },
    { id: 22, category: "Tehsils & Blocks", question: "What is the administrative hierarchy of Kotputli tehsil?", tag: "Hierarchy" },
    { id: 23, category: "Tehsils & Blocks", question: "Details of Dudu tehsil and panchayat samiti.", tag: "Panchayat Samiti" },
    { id: 24, category: "Tehsils & Blocks", question: "What block and tehsil covers Shahpura, Jaipur?", tag: "Block Lineage" },
    { id: 25, category: "Tehsils & Blocks", question: "Administrative details of Phulera tehsil.", tag: "Tehsil Info" },
    { id: 26, category: "Tehsils & Blocks", question: "Details of Viratnagar tehsil and sub-division.", tag: "Sub-Division" },
    { id: 27, category: "Tehsils & Blocks", question: "What is the lineage of Kishangarh Renwal tehsil?", tag: "Lineage" },
    { id: 28, category: "Tehsils & Blocks", question: "Who is the administrative head of Jodhpur tehsil?", tag: "Tehsildar" },
    { id: 29, category: "Tehsils & Blocks", question: "Details of Luni tehsil and panchayat samiti.", tag: "Panchayat Samiti" },
    { id: 30, category: "Tehsils & Blocks", question: "Administrative lineage of Osian tehsil.", tag: "Tehsil Lineage" },

    // 3. Villages & Panchayats (15)
    { id: 31, category: "Villages & Panchayats", question: "What is the administrative lineage of Muhana village?", tag: "Village Lineage" },
    { id: 32, category: "Villages & Panchayats", question: "Who is the Sarpanch and Patwari of Muhana?", tag: "Village Officials" },
    { id: 33, category: "Villages & Panchayats", question: "What is the Gram Panchayat and Patwar Circle of Bagru village?", tag: "Gram Panchayat" },
    { id: 34, category: "Villages & Panchayats", question: "Administrative hierarchy of Bilwa village.", tag: "Village Lineage" },
    { id: 35, category: "Villages & Panchayats", question: "Details of Watika village and gram panchayat.", tag: "Panchayat Info" },
    { id: 36, category: "Villages & Panchayats", question: "Administrative lineage of Chomu village.", tag: "Village Lineage" },
    { id: 37, category: "Villages & Panchayats", question: "What tehsil and block does Goner village fall under?", tag: "Tehsil Mapping" },
    { id: 38, category: "Villages & Panchayats", question: "Lineage of Achrol village in Jaipur.", tag: "Lineage" },
    { id: 39, category: "Villages & Panchayats", question: "Details of Bassi village gram panchayat.", tag: "Gram Panchayat" },
    { id: 40, category: "Villages & Panchayats", question: "Who heads the gram panchayat of Bhanpur Kalan?", tag: "Sarpanch" },
    { id: 41, category: "Villages & Panchayats", question: "Administrative details of Kukas village.", tag: "Village Info" },
    { id: 42, category: "Villages & Panchayats", question: "What patwar circle covers Kanota village?", tag: "Patwar Circle" },
    { id: 43, category: "Villages & Panchayats", question: "Details of village Mohanpura in Sanganer.", tag: "Village Mapping" },
    { id: 44, category: "Villages & Panchayats", question: "What is the administrative hierarchy of village Dantli?", tag: "Hierarchy" },
    { id: 45, category: "Villages & Panchayats", question: "Lineage of village Luniyawas and its patwar circle.", tag: "Patwar Circle" },

    // 4. Urban Bodies & Wards (12)
    { id: 46, category: "Urban Bodies & Wards", question: "What urban local body covers Malviya Nagar, Jaipur?", tag: "ULB Coverage" },
    { id: 47, category: "Urban Bodies & Wards", question: "Details of Jaipur Greater Municipal Corporation.", tag: "Nagar Nigam" },
    { id: 48, category: "Urban Bodies & Wards", question: "Details of Jaipur Heritage Municipal Corporation.", tag: "Nagar Nigam" },
    { id: 49, category: "Urban Bodies & Wards", question: "What urban body governs Sanganer town?", tag: "Municipal Body" },
    { id: 50, category: "Urban Bodies & Wards", question: "Details of Bagru Municipal Board (Nagar Palika).", tag: "Nagar Palika" },
    { id: 51, category: "Urban Bodies & Wards", question: "What is the urban local body type of Chomu?", tag: "ULB Classification" },
    { id: 52, category: "Urban Bodies & Wards", question: "Details of Shahpura Nagar Palika in Jaipur.", tag: "Nagar Palika" },
    { id: 53, category: "Urban Bodies & Wards", question: "What municipal corporation administers Jodhpur city?", tag: "City Governance" },
    { id: 54, category: "Urban Bodies & Wards", question: "Details of Kota Municipal Corporation (North and South).", tag: "Municipal Corp" },
    { id: 55, category: "Urban Bodies & Wards", question: "What urban local body covers Ajmer city?", tag: "Nagar Nigam" },
    { id: 56, category: "Urban Bodies & Wards", question: "Details of Udaipur Municipal Corporation (Nagar Nigam).", tag: "Municipal Corp" },
    { id: 57, category: "Urban Bodies & Wards", question: "What urban body administers Bikaner municipal area?", tag: "City Administration" },

    // 5. Pincodes & Postal (12)
    { id: 58, category: "Pincodes & Postal", question: "Details of pincode 302029.", tag: "Pincode Lineage" },
    { id: 59, category: "Pincodes & Postal", question: "What administrative hierarchy covers pincode 302001?", tag: "Postal Hierarchy" },
    { id: 60, category: "Pincodes & Postal", question: "Which district and tehsil does pincode 302015 belong to?", tag: "Pincode Mapping" },
    { id: 61, category: "Pincodes & Postal", question: "Administrative lineage of pincode 302002.", tag: "Lineage" },
    { id: 62, category: "Pincodes & Postal", question: "Details of pincode 302017 (Malviya Nagar).", tag: "Postal Details" },
    { id: 63, category: "Pincodes & Postal", question: "What area and tehsil is covered under pincode 302020?", tag: "Area Mapping" },
    { id: 64, category: "Pincodes & Postal", question: "Details of pincode 302028 (Pratap Nagar).", tag: "Postal Lineage" },
    { id: 65, category: "Pincodes & Postal", question: "What administrative division covers pincode 302012?", tag: "Division Mapping" },
    { id: 66, category: "Pincodes & Postal", question: "Details of pincode 302033 (Sanganer area).", tag: "Postal Code" },
    { id: 67, category: "Pincodes & Postal", question: "Which tehsil does pincode 303007 belong to?", tag: "Tehsil Postal" },
    { id: 68, category: "Pincodes & Postal", question: "Details of pincode 303103 (Chomu).", tag: "Postal Details" },
    { id: 69, category: "Pincodes & Postal", question: "What area and block does pincode 303901 cover?", tag: "Block Postal" },

    // 6. Officials & Governance (12)
    { id: 70, category: "Officials & Governance", question: "Who is the District Collector and Zila Pramukh of Jaipur?", tag: "District Heads" },
    { id: 71, category: "Officials & Governance", question: "Who heads the Rajasthan State Secretariat?", tag: "Chief Secretary" },
    { id: 72, category: "Officials & Governance", question: "What is the role and jurisdiction of a Sub-Divisional Magistrate (SDM)?", tag: "SDM Role" },
    { id: 73, category: "Officials & Governance", question: "Who is the Divisional Commissioner of Jaipur Division?", tag: "Commissioner" },
    { id: 74, category: "Officials & Governance", question: "What are the duties of a Tehsildar vs a Block Development Officer (BDO)?", tag: "Tehsildar & BDO" },
    { id: 75, category: "Officials & Governance", question: "Who is the administrative head of a Gram Panchayat?", tag: "Sarpanch" },
    { id: 76, category: "Officials & Governance", question: "What does a Patwari do in a Patwar Circle?", tag: "Revenue Official" },
    { id: 77, category: "Officials & Governance", question: "Who heads the Zila Parishad at the district level?", tag: "Zila Pramukh" },
    { id: 78, category: "Officials & Governance", question: "What is the administrative difference between Nagar Nigam and Nagar Palika?", tag: "ULB Hierarchy" },
    { id: 79, category: "Officials & Governance", question: "What official authority manages law and order in a Sub-Division?", tag: "Sub-Division" },
    { id: 80, category: "Officials & Governance", question: "Who heads the municipal corporation (Mayor vs Commissioner)?", tag: "Urban Authority" },
    { id: 81, category: "Officials & Governance", question: "What authority is responsible for land revenue records in a Tehsil?", tag: "Tehsil Authority" },

    // 7. Hindi / हिंदी प्रश्न (12)
    { id: 82, category: "Hindi / हिंदी प्रश्न", question: "मुहाना गांव की प्रशासनिक व राजस्व वंशावली क्या है?", tag: "ग्राम वंशावली" },
    { id: 83, category: "Hindi / हिंदी प्रश्न", question: "बालोतरा जिला किस संभाग के अंतर्गत आता है?", tag: "संभाग मैपिंग" },
    { id: 84, category: "Hindi / हिंदी प्रश्न", question: "राजस्थान के सभी 10 संभागों के नाम बताएं।", tag: "संभाग सूची" },
    { id: 85, category: "Hindi / हिंदी प्रश्न", question: "सांगानेर तहसील किस उपखंड और जिले में है?", tag: "तहसील व उपखंड" },
    { id: 86, category: "Hindi / हिंदी प्रश्न", question: "पिनकोड 302029 का प्रशासनिक विवरण क्या है?", tag: "पिनकोड विवरण" },
    { id: 87, category: "Hindi / हिंदी प्रश्न", question: "जयपुर ग्रेटर नगर निगम के अधिकार क्षेत्र में कौन से क्षेत्र आते हैं?", tag: "नगर निगम" },
    { id: 88, category: "Hindi / हिंदी प्रश्न", question: "बगरू ग्राम पंचायत और पटवार वृत्त का विवरण क्या है?", tag: "पटवार वृत्त" },
    { id: 89, category: "Hindi / हिंदी प्रश्न", question: "डीडवाना-कुचामन जिले का संभाग कौन सा है?", tag: "नया जिला" },
    { id: 90, category: "Hindi / हिंदी प्रश्न", question: "राजस्थान में कुल कितने जिले और संभाग हैं?", tag: "सांख्यिकी" },
    { id: 91, category: "Hindi / हिंदी प्रश्न", question: "ब्यावर जिला किस संभाग में आता है?", tag: "जिला संभाग" },
    { id: 92, category: "Hindi / हिंदी प्रश्न", question: "ग्राम पंचायत का मुखिया कौन होता है?", tag: "सरपंच" },
    { id: 93, category: "Hindi / हिंदी प्रश्न", question: "अनूपगढ़ जिले का प्रशासनिक पदानुक्रम क्या है?", tag: "पदानुक्रम" },

    // 8. Out-of-Scope Guardrails (8)
    { id: 94, category: "Out-of-Scope Guardrails", question: "Write python code for sorting an array", tag: "Guardrail (Code)" },
    { id: 95, category: "Out-of-Scope Guardrails", question: "What is the weather in Jaipur today?", tag: "Guardrail (Weather)" },
    { id: 96, category: "Out-of-Scope Guardrails", question: "Who won the cricket match yesterday?", tag: "Guardrail (Sports)" },
    { id: 97, category: "Out-of-Scope Guardrails", question: "Explain how to invest in cryptocurrency", tag: "Guardrail (Finance)" },
    { id: 98, category: "Out-of-Scope Guardrails", question: "What is the latest movie release this week?", tag: "Guardrail (Cinema)" },
    { id: 99, category: "Out-of-Scope Guardrails", question: "Write an essay on global warming", tag: "Guardrail (Essay)" },
    { id: 100, category: "Out-of-Scope Guardrails", question: "Tell me a joke about programming", tag: "Guardrail (Joke)" },
    { id: 101, category: "Out-of-Scope Guardrails", question: "What is the Rajasthan government helpline number?", tag: "Helpline Lookup" }
  ];

  copiedMessageId: string | null = null;

  // --- WhatsApp-Style Inactivity Privacy Shield (Req 7 & Activity Enhancement) ---
  autoHideMinutes: number = 2; // User-selectable: 0 (Off/Manual), 1, 2, 5
  inactivitySecondsRemaining: number = 120; // 2 minutes default
  isChatHidden: boolean = false;
  private inactivityInterval: any = null;
  private lastActivityThrottle: number = 0;
  private manualHideUntil: number = 0;
  private readonly activityEvents: string[] = [
    'mousemove',
    'pointermove',
    'mousedown',
    'click',
    'keydown',
    'touchstart',
    'pointerdown',
    'wheel',
    'scroll'
  ];
  private activityListener = () => this.onUserActivity();

  // --- User Auth & Profile Modal (Req 8) ---
  isUserAuthModalOpen: boolean = false;
  userAuthTab: 'login' | 'register' | 'profile' = 'login';
  userLoginForm = { username: '', password: '' };
  userRegisterForm = { name: '', username: '', phone: '', email: '', password: '', preferred_language: 'en' };
  userProfileForm = { name: '', phone: '', email: '', preferred_language: 'en' };
  userAuthNotice: string = '';
  isUserAuthLoading: boolean = false;

  // --- First-Time Greeting & Respectful Name Capture (Req 9) ---
  isAwaitingName: boolean = true;
  hasCapturedName: boolean = false;

  constructor(
    public chatService: ChatService,
    public auth: AuthService,
    public userService: UserService,
    private sanitizer: DomSanitizer
  ) {}

  setViewMode(msg: ChatMessage, mode: 'preview' | 'raw'): void {
    msg.viewMode = mode;
  }

  copyToClipboard(text: string, msgId: string): void {
    if (navigator && navigator.clipboard) {
      navigator.clipboard.writeText(text);
    }
    this.copiedMessageId = msgId;
    setTimeout(() => {
      if (this.copiedMessageId === msgId) {
        this.copiedMessageId = null;
      }
    }, 2000);
  }

  renderMarkdown(content: string): SafeHtml {
    if (!content) return '';

    let text = content;

    // 1. Escape HTML special characters
    text = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Strip duplicate "Next Expected Questions" / "अगले अपेक्षित प्रश्न" list from text body so it only shows as the interactive link chips below
    text = text.replace(
      /(?:\n+|^)(?:💡\s*)?(?:\*\*\s*)?(?:Next Expected Questions|अगले प्रश्न|अगले अपेक्षित प्रश्न)(?::)?(?:\s*\*\*)?:?\s*\n+(?:(?:\d+\.|\-|\*|➔)\s+[^\n]+\n*)+/gi,
      ''
    );
    text = text.replace(
      /(?:\n+|^)(?:💡\s*)?(?:\*\*\s*)?(?:Next Expected Questions|अगले प्रश्न|अगले अपेक्षित प्रश्न)(?::)?(?:\s*\*\*)?:?\s*$/gi,
      ''
    );

    // Strip "Hierarchy Path (Administrative Lineage) 6-Tier Master Path" / "Administrative Hierarchy Breadcrumb" box as requested
    text = text.replace(
      /(?:📌\s*)?(?:\*\*\s*)?(?:Hierarchy Path|Administrative Hierarchy Breadcrumb|पदानुक्रम मार्ग\s*(?:\(Hierarchy Path\))?|पदानुक्रम मार्ग)(?::)?(?:\s*\*\*)?:?\s*\n+(?:`([^`\n]+)`|([^\n💡🏛️#\r]+(?:➔|->)[^\n💡🏛️#\r]+))/gi,
      ''
    );

    // 3. Governance & Administrative Authority Section
    text = text.replace(
      /(?:🏛️\s*)?(?:\*\*\s*)?(Governance & Administrative Authority|Governance & Administrative Details|प्रशासनिक नियंत्रण एवं प्रमुख अधिकारी)(?::)?(?:\s*\*\*)?:?\s*\n+([^💡#\n]+(?:\n(?!💡|#|\n)[^\n]+)*)/gi,
      (_match, title, body) => {
        return `<div class="my-3.5 p-4 rounded-2xl bg-gradient-to-br from-slate-50 via-white to-slate-50/70 border border-slate-200 shadow-xs">
          <div class="flex items-center space-x-2 border-b border-slate-200/80 pb-2 mb-2.5">
            <span class="flex items-center justify-center w-6 h-6 rounded-lg bg-slate-200/80 text-slate-700 text-xs font-bold">🏛️</span>
            <span class="text-xs sm:text-sm font-black tracking-wide uppercase text-slate-900 underline decoration-slate-400 decoration-2 underline-offset-4">${title.trim()}</span>
          </div>
          <div class="text-xs sm:text-sm text-slate-700 leading-relaxed font-normal">${body.trim()}</div>
        </div>`;
      }
    );

    // 3b. Next Expected Questions Section Header
    text = text.replace(
      /(?:💡\s*)?(?:\*\*\s*)?(Next Expected Questions|अगले अपेक्षित प्रश्न(?:\s*\(Next Expected Questions\))?)(?::)?(?:\s*\*\*)?:?\s*\n+/gi,
      (_match, title) => {
        return `<div class="mt-4 mb-2 flex items-center space-x-2 border-b border-amber-200/80 pb-1.5">
          <span class="flex items-center justify-center w-5 h-5 rounded-md bg-amber-100 text-amber-800 text-xs font-bold">💡</span>
          <span class="text-xs font-black tracking-wide uppercase text-slate-900 underline decoration-amber-400 decoration-2 underline-offset-4">${title.trim()}</span>
        </div>`;
      }
    );

    // 4. Headings
    text = text.replace(/^### (.*$)/gim, '<h3 class="text-sm font-bold text-slate-900 mt-3 mb-1.5 flex items-center space-x-1.5"><span class="w-1.5 h-3.5 bg-orange-600 rounded-full inline-block"></span><span>$1</span></h3>');
    text = text.replace(/^#### (.*$)/gim, '<h4 class="text-xs font-bold text-slate-700 uppercase tracking-wider mt-2.5 mb-1">$1</h4>');

    // 5. Inline code
    text = text.replace(/`([^`]+)`/g, '<code class="px-2 py-0.5 rounded-md bg-orange-50 text-orange-950 font-mono text-xs border border-orange-200/80 font-bold">$1</code>');

    // 6. Bold & Asterisk Stripping
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-slate-900 underline decoration-orange-300 decoration-1 underline-offset-2">$1</strong>');
    text = text.replace(/\*\*/g, '');

    // 7. Italic
    text = text.replace(/\*([^*]+)\*/g, '<em class="italic text-slate-800">$1</em>');

    // 8. Markdown Links
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-orange-600 font-bold hover:underline inline-flex items-center space-x-0.5" target="_blank" rel="noopener noreferrer"><span>$1</span></a>');

    // 9. Numbered lists
    text = text.replace(/^(\d+)\.\s+(.*$)/gim, '<div class="flex items-start space-x-2 my-1 pl-1"><span class="w-4 h-4 rounded-full bg-orange-100 text-orange-800 text-[10px] font-extrabold flex items-center justify-center shrink-0 mt-0.5">$1</span><span class="text-xs sm:text-sm text-slate-800 leading-relaxed">$2</span></div>');

    // 10. Bullet lists
    text = text.replace(/^[•\-\*]\s+(.*$)/gim, '<div class="flex items-start space-x-2 my-1 pl-1"><span class="text-orange-500 font-bold text-xs mt-0.5">•</span><span class="text-xs sm:text-sm text-slate-800 leading-relaxed">$1</span></div>');

    // 11. Paragraphs
    const paragraphs = text.split(/\n{2,}/);
    const html = paragraphs
      .map(p => {
        const trimmed = p.trim();
        if (!trimmed) return '';
        if (trimmed.startsWith('<div') || trimmed.startsWith('<h3') || trimmed.startsWith('<h4')) {
          return trimmed;
        }
        return `<p class="mb-2 leading-relaxed text-xs sm:text-sm text-slate-800">${trimmed.replace(/\n/g, '<br/>')}</p>`;
      })
      .join('');

    return this.sanitizer.bypassSecurityTrustHtml(html);
  }

  ngOnInit(): void {
    this.initInactivityTimer();
    this.loadCapabilities();
    this.loadMcpStatus();
    this.loadExampleQuestions();
  }

  loadMcpStatus(): void {
    this.chatService.getMcpStatus().subscribe({
      next: (res) => {
        this.mcpStatus = res;
      },
      error: () => {
        this.mcpStatus = null;
      }
    });
  }

  ngOnDestroy(): void {
    if (this.inactivityInterval) {
      clearInterval(this.inactivityInterval);
    }
    if (typeof window !== 'undefined') {
      this.activityEvents.forEach((evt) => {
        window.removeEventListener(evt, this.activityListener, true);
        window.removeEventListener(evt, this.activityListener, false);
      });
    }
  }

  // --- WhatsApp-Style Inactivity Privacy Shield Methods (Req 7 & Activity Tracking) ---
  private initInactivityTimer(): void {
    if (typeof window !== 'undefined') {
      const savedMins = Number(localStorage.getItem('rajmaster_chat_autohide_minutes'));
      if ([0, 1, 2, 5].includes(savedMins)) {
        this.autoHideMinutes = savedMins;
      }
      this.activityEvents.forEach((evt) => {
        window.addEventListener(evt, this.activityListener, { passive: true, capture: true });
      });
    }

    this.inactivitySecondsRemaining = this.autoHideMinutes > 0 ? this.autoHideMinutes * 60 : 120;
    this.isChatHidden = false;

    if (this.inactivityInterval) {
      clearInterval(this.inactivityInterval);
    }

    this.inactivityInterval = setInterval(() => {
      if (!this.isChatHidden && this.autoHideMinutes > 0 && this.inactivitySecondsRemaining > 0) {
        this.inactivitySecondsRemaining--;
        if (this.inactivitySecondsRemaining === 0) {
          this.isChatHidden = true; // Auto-hide chat after inactivity timeout
        }
      }
    }, 1000);
  }

  setAutoHideMinutes(mins: number): void {
    const valid = [0, 1, 2, 5].includes(mins) ? mins : 2;
    this.autoHideMinutes = valid;
    if (typeof window !== 'undefined') {
      localStorage.setItem('rajmaster_chat_autohide_minutes', String(valid));
    }
    this.inactivitySecondsRemaining = valid > 0 ? valid * 60 : 120;
  }

  onUserActivity(): void {
    const now = Date.now();
    // Do not auto-unhide if user just clicked the manual "Hide Chat" button within the last 1.2s
    if (now < this.manualHideUntil) {
      return;
    }

    // Moving mouse or clicking actively unhides the chat if obscured
    if (this.isChatHidden) {
      this.isChatHidden = false;
    }

    // Throttle resetting the inactivity seconds remaining counter to once every 200ms
    if (now - this.lastActivityThrottle < 200) {
      return;
    }
    this.lastActivityThrottle = now;

    if (this.autoHideMinutes > 0) {
      this.inactivitySecondsRemaining = this.autoHideMinutes * 60;
    }
  }

  toggleChatPrivacy(): void {
    if (!this.isChatHidden) {
      this.manualHideUntil = Date.now() + 1200;
      this.isChatHidden = true;
    } else {
      this.isChatHidden = false;
      this.inactivitySecondsRemaining = this.autoHideMinutes > 0 ? this.autoHideMinutes * 60 : 120;
    }
  }

  hideChatNow(): void {
    this.manualHideUntil = Date.now() + 1200;
    this.isChatHidden = true;
  }

  revealChat(): void {
    this.isChatHidden = false;
    this.inactivitySecondsRemaining = this.autoHideMinutes > 0 ? this.autoHideMinutes * 60 : 120;
  }

  get formattedInactivityTime(): string {
    if (this.autoHideMinutes === 0) {
      return 'Manual';
    }
    const mins = Math.floor(this.inactivitySecondsRemaining / 60);
    const secs = this.inactivitySecondsRemaining % 60;
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  }

  // --- User Auth & Profile Modal Methods (Req 8) ---
  openUserAuthModal(tab: 'login' | 'register' | 'profile' = 'login'): void {
    this.userAuthNotice = '';
    const current = this.userService.currentUser();
    if (this.userService.isLoggedIn() && current) {
      this.userAuthTab = 'profile';
      if (tab === 'login' || tab === 'register') {
        this.userAuthNotice = `User "${current.name || current.username}" is already logged in. Please sign out first to log in another user.`;
      }
      this.userProfileForm = {
        name: current.name || '',
        phone: current.phone || '',
        email: current.email || '',
        preferred_language: current.preferred_language || 'en'
      };
    } else {
      this.userAuthTab = tab === 'profile' ? 'login' : tab;
    }
    this.isUserAuthModalOpen = true;
  }

  closeUserAuthModal(): void {
    this.isUserAuthModalOpen = false;
    this.userAuthNotice = '';
  }

  onUserLogin(): void {
    if (this.userService.isLoggedIn()) {
      const cur = this.userService.currentUser();
      this.userAuthTab = 'profile';
      this.userAuthNotice = `User "${cur?.name || cur?.username}" is already logged in. Sign out first to switch accounts.`;
      return;
    }
    if (!this.userLoginForm.username.trim() || !this.userLoginForm.password.trim()) {
      this.userAuthNotice = 'Please enter both username and password.';
      return;
    }
    this.isUserAuthLoading = true;
    this.userAuthNotice = 'Signing in...';
    this.userService.login(this.userLoginForm.username.trim(), this.userLoginForm.password).subscribe({
      next: (res) => {
        this.isUserAuthLoading = false;
        this.userLoginForm.password = '';
        this.userAuthNotice = `✓ Welcome back, ${res.user.name || res.user.username} ji!`;
        this.updateGreetingForUser(res.user.name);
        setTimeout(() => this.closeUserAuthModal(), 1200);
      },
      error: (err) => {
        this.isUserAuthLoading = false;
        this.userAuthNotice = 'Login error: ' + (err.error?.detail || err.message || 'Invalid credentials.');
      }
    });
  }

  onUserRegister(): void {
    if (this.userService.isLoggedIn()) {
      const cur = this.userService.currentUser();
      this.userAuthTab = 'profile';
      this.userAuthNotice = `User "${cur?.name || cur?.username}" is already logged in. Sign out first to register another user.`;
      return;
    }
    if (!this.userRegisterForm.name.trim() || !this.userRegisterForm.username.trim()) {
      this.userAuthNotice = 'Please enter your full name and a username / mobile.';
      return;
    }
    if (!this.userRegisterForm.password || this.userRegisterForm.password.trim().length < 4) {
      this.userAuthNotice = 'Please create a password of at least 4 characters.';
      return;
    }
    this.isUserAuthLoading = true;
    this.userAuthNotice = 'Creating user profile...';
    this.userService.register(this.userRegisterForm).subscribe({
      next: (res) => {
        this.isUserAuthLoading = false;
        this.userRegisterForm.password = '';
        this.userAuthNotice = `✓ Profile created successfully! Welcome, ${res.user.name} ji!`;
        this.updateGreetingForUser(res.user.name);
        setTimeout(() => this.closeUserAuthModal(), 1200);
      },
      error: (err) => {
        this.isUserAuthLoading = false;
        this.userAuthNotice = 'Registration error: ' + (err.error?.detail || err.message || 'Registration failed.');
      }
    });
  }

  onUpdateUserProfile(): void {
    if (!this.userProfileForm.name.trim()) {
      this.userAuthNotice = 'Name cannot be empty.';
      return;
    }
    this.isUserAuthLoading = true;
    this.userAuthNotice = 'Saving profile changes...';
    this.userService.updateProfile(this.userProfileForm).subscribe({
      next: (res) => {
        this.isUserAuthLoading = false;
        this.userAuthNotice = '✓ Profile updated successfully!';
        setTimeout(() => this.closeUserAuthModal(), 1200);
      },
      error: (err) => {
        this.isUserAuthLoading = false;
        this.userAuthNotice = 'Update error: ' + (err.error?.detail || err.message);
      }
    });
  }

  onUserLogout(): void {
    this.userService.logout();
    this.closeUserAuthModal();
  }

  // --- Respectful First-Time Greeting & Name Setup (Req 9) ---
  private setupInitialGreeting(customGreeting?: string): void {
    const user = this.userService.currentUser();
    const userName = (user?.name || this.userService.guestName() || '').trim();

    let greetingText = '';
    if (userName) {
      this.isAwaitingName = false;
      this.hasCapturedName = true;
      greetingText = `नमस्ते **${userName} जी**! 🙏\n\nWelcome to this **Full-Stack AI & LLM Engineering Portfolio Showcase** (Demonstrating LangGraph, Multi-Cloud LLMs, Python FastAPI, and PostgreSQL Hierarchy).\n\nआप राजस्थान के किसी भी जिले, तहसील, उपखंड, गांव, नगरीय निकाय या 6-डिजिट पिनकोड के बारे में पूछ सकते हैं। How may I assist you today?`;
    } else {
      this.isAwaitingName = true;
      this.hasCapturedName = false;
      greetingText = `नमस्ते! 🙏\n\nWelcome to this **Full-Stack AI & LLM Architecture Portfolio Showcase** (Demonstrating LangGraph Multi-Agent Workflows, Multi-Cloud LLM Failovers, Python FastAPI, and PostgreSQL Vector RAG).\n\nबातचीत शुरू करने से पहले, क्या मैं आदरपूर्वक आपका **शुभ नाम** जान सकता हूँ? 🙏\n*(Before we proceed, may I respectfully know your good name?)*`;
    }

    if (this.messages.length === 0) {
      this.messages.push({
        id: 'init-msg',
        sender: 'assistant',
        text: greetingText,
        timestamp: new Date(),
        intent: 'capability_query',
        supportPhone: this.supportPhone
      });
    }
  }

  private updateGreetingForUser(name: string): void {
    if (!name) return;
    this.hasCapturedName = true;
    this.isAwaitingName = false;
    const initMsg = this.messages.find(m => m.id === 'init-msg' || m.id === 'init-fallback');
    if (initMsg) {
      initMsg.text = `नमस्ते **${name} जी**! 🙏\n\nWelcome to this **Full-Stack AI & LLM Engineering Portfolio Showcase**.\n\nDemonstrating LangGraph multi-agent orchestration, multi-cloud LLM routing, and PostgreSQL Vector RAG across Rajasthan's 10 divisions, 50 districts, tehsils, and pincodes. How may I assist you today?`;
    }
  }

  ngAfterViewChecked(): void {
    this.scrollToBottom();
  }

  loadCapabilities(): void {
    this.chatService.getCapabilities().subscribe({
      next: (data) => {
        this.capabilities = data;
        if (data.support_phone) {
          this.supportPhone = data.support_phone;
        }
        if (data.sample_prompts && data.sample_prompts.length > 0) {
          this.quickChips = data.sample_prompts;
        }
        this.setupInitialGreeting(data.greeting);
      },
      error: () => {
        this.setupInitialGreeting();
      }
    });
  }

  loadExampleQuestions(): void {
    this.chatService.getExampleQuestions().subscribe({
      next: (res) => {
        if (res && res.questions && res.questions.length > 0) {
          this.allQuestions = res.questions;
          if (res.categories && res.categories.length > 0) {
            this.questionCategories = res.categories;
          }
        }
      },
      error: () => {
        // Fallback array remains intact
      }
    });
  }

  // Modal Handlers
  openQuestionsModal(): void {
    this.isQuestionsModalOpen = true;
  }

  closeQuestionsModal(): void {
    this.isQuestionsModalOpen = false;
  }

  setCategory(category: string): void {
    this.selectedCategory = category;
  }

  get filteredQuestions(): ExampleQuestion[] {
    const term = this.questionSearchTerm.trim().toLowerCase();
    return this.allQuestions.filter(q => {
      const matchCat = this.selectedCategory === 'All' || q.category === this.selectedCategory;
      const matchSearch = !term ||
        q.question.toLowerCase().includes(term) ||
        q.tag.toLowerCase().includes(term) ||
        q.category.toLowerCase().includes(term);
      return matchCat && matchSearch;
    });
  }

  askQuestion(questionText: string): void {
    this.closeQuestionsModal();
    this.closeAboutModal();
    this.closeTextFlowModal();
    this.closeAudioFlowModal();
    this.inputQuery = questionText;
    this.sendMessage();
  }

  toggleSidebar(): void {
    this.isSidebarOpen = !this.isSidebarOpen;
  }

  useChip(prompt: string): void {
    this.inputQuery = prompt;
    this.sendMessage();
  }

  sendMessage(): void {
    const q = this.inputQuery.trim();
    if (!q || this.isStreaming) return;

    // Reset inactivity privacy timer on user activity
    this.resetInactivityTimer();

    // Check if awaiting respectful user name (Req 9)
    if (this.isAwaitingName && !this.hasCapturedName) {
      const trimmed = q.trim();
      const nameMatch = trimmed.match(/(?:mera\s+naam|my\s+name\s+is|i\s+am|i'm|naam\s+hai|main\s+hoon|naam\s+h|naam)\s+([A-Za-z\u0900-\u097F\s]{2,30})/i);
      let detectedName = '';
      if (nameMatch && nameMatch[1]) {
        detectedName = nameMatch[1].replace(/(?:hai|hoon|ji|sir|madam)/gi, '').trim();
      } else if (trimmed.split(/\s+/).length <= 4 && !/^(what|where|how|tell|list|which|details|pincode|village|tehsil|district|division|kon|kaun|kahan|kya)/i.test(trimmed)) {
        detectedName = trimmed.replace(/^(i am|my name is|mera naam|naam|main)\s*/i, '').replace(/(?:hai|hoon|ji|sir|madam)/gi, '').trim();
      }

      if (detectedName && detectedName.length >= 2) {
        this.hasCapturedName = true;
        this.isAwaitingName = false;
        this.userService.setUserName(detectedName);

        // Append user message
        this.messages.push({
          id: 'usr-' + Date.now(),
          sender: 'user',
          text: q,
          timestamp: new Date()
        });
        this.inputQuery = '';

        // Respectful assistant response acknowledging name
        setTimeout(() => {
          this.messages.push({
            id: 'bot-name-ack-' + Date.now(),
            sender: 'assistant',
            text: `बहुत-बहुत धन्यवाद **${detectedName} जी**! 🙏\n\nआपसे जुड़कर अत्यंत प्रसन्नता हुई।\n\nयह प्रोजेक्ट modern AI, LLM, LangGraph, Python FastAPI और Full-Stack आर्किटेक्चर की क्षमताओं को प्रदर्शित करने के लिए बनाया गया एक पोर्टफोलियो शोकेस है।\n\nअब आप राजस्थान के किसी भी जिले, तहसील, उपखंड, गांव, नगरीय निकाय या पिनकोड के बारे में कोई भी प्रश्न पूछ सकते हैं!`,
            timestamp: new Date(),
            intent: 'capability_query',
            supportPhone: this.supportPhone
          });
        }, 300);
        return;
      } else {
        // User asked a question directly, proceed with normal answering
        this.isAwaitingName = false;
      }
    }

    // Append user message
    const userMsg: ChatMessage = {
      id: 'usr-' + Date.now(),
      sender: 'user',
      text: q,
      timestamp: new Date()
    };
    this.messages.push(userMsg);
    this.inputQuery = '';

    // Create assistant placeholder message
    const botMsgId = 'bot-' + Date.now();
    const botMsg: ChatMessage = {
      id: botMsgId,
      sender: 'assistant',
      text: '',
      timestamp: new Date(),
      isStreaming: true,
      viewMode: 'preview'
    };
    this.messages.push(botMsg);
    this.isStreaming = true;

    this.chatService.streamMessage(
      this.sessionId,
      q,
      (token: string) => {
        const msg = this.messages.find(m => m.id === botMsgId);
        if (msg) {
          msg.text += token.replace(/\*\*/g, '');
        }
      },
      (meta: any) => {
        const msg = this.messages.find(m => m.id === botMsgId);
        if (msg) {
          msg.isStreaming = false;
          msg.intent = meta.intent;
          msg.language = meta.language;
          msg.nextQuestions = meta.next_questions || [];
          msg.breadcrumbs = meta.breadcrumbs;
          msg.helplineCard = meta.helpline_card;
          msg.supportPhone = meta.support_phone || this.supportPhone;
          msg.mcpUsed = Boolean(meta.mcp_used);
          msg.mcpTool = meta.mcp_tool;
          msg.mcpTransport = meta.mcp_transport;
          msg.resolutionStage = meta.resolution_stage;
        }
        this.isStreaming = false;
      },
      (err: any) => {
        console.warn('Streaming error, falling back to standard POST /api/chat:', err);
        // Fallback to standard HTTP POST /api/chat if streaming is interrupted
        this.chatService.sendMessage(this.sessionId, q, this.selectedLanguage).subscribe({
          next: (res) => {
            const msg = this.messages.find(m => m.id === botMsgId);
            if (msg) {
              msg.isStreaming = false;
              msg.text = (res.response || '').replace(/\*\*/g, '');
              msg.intent = res.intent;
              msg.language = res.language;
              msg.nextQuestions = res.next_questions || [];
              msg.breadcrumbs = res.breadcrumbs;
              msg.helplineCard = res.helpline_card;
              msg.supportPhone = res.support_phone || this.supportPhone;
              msg.mcpUsed = Boolean(res.mcp_used);
              msg.mcpTool = res.mcp_tool;
              msg.mcpTransport = res.mcp_transport;
              msg.resolutionStage = res.resolution_stage;
            }
            this.isStreaming = false;
          },
          error: (fallbackErr) => {
            console.error('Chat fallback error:', fallbackErr);
            const msg = this.messages.find(m => m.id === botMsgId);
            if (msg) {
              msg.isStreaming = false;
              msg.text = `I encountered a connection issue while searching the knowledge graph. Please try again or call our helpline at ${this.supportPhone}.`;
              msg.helplineCard = true;
              msg.supportPhone = this.supportPhone;
            }
            this.isStreaming = false;
          }
        });
      },
      this.selectedLanguage
    );
  }

  resetInactivityTimer(): void {
    if (!this.isChatHidden) {
      this.inactivitySecondsRemaining = 120;
    }
  }

  clearChat(): void {
    this.messages = [];
    this.sessionId = 'session-' + Math.random().toString(36).substring(2, 9);
    this.setupInitialGreeting();
  }

  private scrollToBottom(): void {
    try {
      if (this.scrollContainer) {
        this.scrollContainer.nativeElement.scrollTop = this.scrollContainer.nativeElement.scrollHeight;
      }
    } catch (err) {}
  }
}
