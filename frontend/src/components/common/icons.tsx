// ResQWork's own line-icon set (24×24, 2px stroke). Bundled locally so the website has no icon dependency.
import React from 'react';

export interface IconProps { className?: string; style?: React.CSSProperties; 'aria-label'?: string }

function make(name: string, body: React.ReactNode) {
  const Icon = ({ className = 'w-4 h-4', style, ...rest }: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
         className={className} style={style} aria-hidden={rest['aria-label'] ? undefined : true} role={rest['aria-label'] ? 'img' : undefined}
         aria-label={rest['aria-label']} data-icon={name}>
      {body}
    </svg>
  );
  Icon.displayName = name;
  return Icon;
}

const circle = (cx = 12, cy = 12, r = 9) => <circle cx={cx} cy={cy} r={r} />;

export const Activity = make('Activity', <path d="M3 12h4l3 8 4-16 3 8h4" />);
export const AlertOctagon = make('AlertOctagon', <><path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z" /><path d="M12 8v4M12 16h.01" /></>);
export const AlertTriangle = make('AlertTriangle', <><path d="M10.3 4.3 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></>);
export const ArrowRight = make('ArrowRight', <path d="M5 12h14M13 6l6 6-6 6" />);
export const Award = make('Award', <><circle cx="12" cy="9" r="6" /><path d="M8.5 14 7 22l5-3 5 3-1.5-8" /></>);
export const BarChart3 = make('BarChart3', <path d="M3 3v18h18M8 17v-5M13 17V7M18 17v-8" />);
export const Bell = make('Bell', <><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0" /></>);
export const Building2 = make('Building2', <><path d="M6 22V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v18M2 22h20" /><path d="M10 7h4M10 11h4M10 15h4M10 22v-3h4v3" /></>);
export const CalendarDays = make('CalendarDays', <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01" /></>);
export const Check = make('Check', <path d="m5 12 5 5 9-10" />);
export const CheckCircle2 = make('CheckCircle2', <>{circle()}<path d="m8.5 12 2.5 2.5 4.5-5" /></>);
export const ChevronDown = make('ChevronDown', <path d="m6 9 6 6 6-6" />);
export const ChevronUp = make('ChevronUp', <path d="m6 15 6-6 6 6" />);
export const CircleDot = make('CircleDot', <>{circle()}<circle cx="12" cy="12" r="1.5" fill="currentColor" /></>);
export const ClipboardList = make('ClipboardList', <><rect x="5" y="4" width="14" height="18" rx="2" /><path d="M9 2h6v4H9zM9 11h6M9 15h6M9 19h3" /></>);
export const Clock = make('Clock', <>{circle()}<path d="M12 7v5l3 2" /></>);
export const Columns3 = make('Columns3', <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M15 4v16" /></>);
export const Cpu = make('Cpu', <><rect x="6" y="6" width="12" height="12" rx="1" /><path d="M10 10h4v4h-4zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></>);
export const Factory = make('Factory', <path d="M2 21h20M3 21V10l5 3V10l5 3V10l5 3V4h3v17M7 17h2M12 17h2M17 17h2" />);
export const FileClock = make('FileClock', <><path d="M14 2H6a2 2 0 0 0-2 2v8M14 2v6h6M20 8v12a2 2 0 0 1-2 2h-4" /><circle cx="8" cy="17" r="5" /><path d="M8 15v2l1.5 1" /></>);
export const FileJson = make('FileJson', <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M10 12c-1 0-1 1-1 2s-1 1-1 1 1 0 1 1 0 2 1 2M14 12c1 0 1 1 1 2s1 1 1 1-1 0-1 1 0 2-1 2" /></>);
export const FileSpreadsheet = make('FileSpreadsheet', <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 12h8v6H8zM8 15h8M12 12v6" /></>);
export const FileText = make('FileText', <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8M8 17h6" /></>);
export const FlaskConical = make('FlaskConical', <path d="M9 3h6M10 3v6L4.5 19A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3M7 15h10" />);
export const GitCommit = make('GitCommit', <><circle cx="12" cy="12" r="3.5" /><path d="M2 12h6.5M15.5 12H22" /></>);
export const GraduationCap = make('GraduationCap', <path d="M2 9l10-5 10 5-10 5zM6 11v5c3 3 9 3 12 0v-5M22 9v6" />);
export const Hand = make('Hand', <path d="M8 12V5a1.5 1.5 0 0 1 3 0v6M11 10V3.5a1.5 1.5 0 0 1 3 0V10M14 10V5a1.5 1.5 0 0 1 3 0v8c0 5-3 8-7 8-3 0-5-2-6.5-5L3 13a1.5 1.5 0 0 1 2.5-1.5L8 14" />);
export const HeartPulse = make('HeartPulse', <><path d="M19.5 13.5 12 21l-7.5-7.5A5 5 0 0 1 12 6a5 5 0 0 1 7.5 7.5z" /><path d="M3 12h5l2-3 3 6 2-3h6" /></>);
export const HelpCircle = make('HelpCircle', <>{circle()}<path d="M9.5 9a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 2.2-2.4 3.7M12 17h.01" /></>);
export const History = make('History', <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>);
export const Inbox = make('Inbox', <path d="M22 12h-6l-2 3h-4l-2-3H2M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z" />);
export const Info = make('Info', <>{circle()}<path d="M12 16v-5M12 8h.01" /></>);
export const KeyRound = make('KeyRound', <><circle cx="15.5" cy="8.5" r="5.5" /><path d="M11.6 12.4 3 21v-3h3v-3h3l2.6-2.6M16 8h.01" /></>);
export const LayoutDashboard = make('LayoutDashboard', <><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></>);
export const Lightbulb = make('Lightbulb', <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.3h6c0-1 .4-1.8 1-2.3A7 7 0 0 0 12 2z" />);
export const Loader2 = make('Loader2', <path d="M21 12a9 9 0 1 1-6.2-8.6" />);
export const Lock = make('Lock', <><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>);
export const LogOut = make('LogOut', <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />);
export const MessageSquare = make('MessageSquare', <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />);
export const Mic = make('Mic', <><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8" /></>);
export const PenLine = make('PenLine', <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />);
export const Plus = make('Plus', <path d="M12 5v14M5 12h14" />);
export const RefreshCcw = make('RefreshCcw', <path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5" />);
export const RotateCcw = make('RotateCcw', <path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5" />);
export const Scale = make('Scale', <path d="M12 3v18M7 21h10M3 7h18M6 7l-3 7a3 3 0 0 0 6 0zM18 7l-3 7a3 3 0 0 0 6 0z" />);
export const ScanSearch = make('ScanSearch', <><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2" /><circle cx="11" cy="11" r="3.5" /><path d="m16 16-2.5-2.5" /></>);
export const Search = make('Search', <><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></>);
export const Send = make('Send', <path d="m22 2-7 20-4-9-9-4zM22 2 11 13" />);
export const ShieldCheck = make('ShieldCheck', <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="m9 12 2 2 4-4" /></>);
export const Sparkles = make('Sparkles', <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8zM5 2l.6 1.4L7 4l-1.4.6L5 6l-.6-1.4L3 4l1.4-.6z" />);
export const Square = make('Square', <rect x="5" y="5" width="14" height="14" rx="2" />);
export const Trash2 = make('Trash2', <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" />);
export const Truck = make('Truck', <><path d="M3 5h11v11H3zM14 9h4l3 4v3h-7" /><circle cx="7" cy="18" r="2" /><circle cx="17.5" cy="18" r="2" /></>);
export const Upload = make('Upload', <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />);
export const Users = make('Users', <><circle cx="9" cy="7" r="4" /><path d="M2 21v-1a6 6 0 0 1 12 0v1M16 3.3a4 4 0 0 1 0 7.4M22 21v-1a6 6 0 0 0-4-5.7" /></>);
export const Volume2 = make('Volume2', <path d="M11 5 6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" />);
export const VolumeX = make('VolumeX', <path d="M11 5 6 9H2v6h4l5 4zM22 9l-6 6M16 9l6 6" />);
export const Wrench = make('Wrench', <path d="M14.7 6.3a4 4 0 0 0 5 5L21 13a6 6 0 0 1-7.6 1.4L5.5 22.3a2.1 2.1 0 0 1-3-3l7.9-7.9A6 6 0 0 1 11 3.3l1.7 1.3a4 4 0 0 0 2 1.7z" />);
export const X = make('X', <path d="M18 6 6 18M6 6l12 12" />);
export const XCircle = make('XCircle', <>{circle()}<path d="m15 9-6 6M9 9l6 6" /></>);
export const Zap = make('Zap', <path d="M13 2 3 14h9l-1 8 10-12h-9z" />);
export const Eye = make('Eye', <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>);
export const EyeOff = make('EyeOff', <><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-2.2 3.2M6.6 6.6C3.7 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2M2 2l20 20" /></>);
export const Download = make('Download', <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />);
export const Trophy = make('Trophy', <><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z" /><path d="M7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4" /></>);
export const Star = make('Star', <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9z" />);
export const UserPlus = make('UserPlus', <><circle cx="9" cy="7" r="4" /><path d="M2 21v-1a6 6 0 0 1 12 0v1M19 8v6M16 11h6" /></>);
export const User = make('User', <><circle cx="12" cy="8" r="4" /><path d="M4 21v-1a7 7 0 0 1 16 0v1" /></>);
export const Settings = make('Settings', <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></>);
export const Mail = make('Mail', <><rect x="2" y="4" width="20" height="16" rx="2" /><path d="m22 7-10 6L2 7" /></>);
export const Phone = make('Phone', <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z" />);
export const MessageCircle = make('MessageCircle', <path d="M21 11.5a8.4 8.4 0 0 1-12.4 7.4L3 21l2.1-5.6A8.4 8.4 0 1 1 21 11.5z" />);
export const SlidersHorizontal = make('SlidersHorizontal', <path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4" />);
export const Megaphone = make('Megaphone', <path d="m3 11 18-5v12L3 13zM11.6 16.8a3 3 0 1 1-5.8-1.6" />);
export const TrendingUp = make('TrendingUp', <path d="m22 7-8.5 8.5-5-5L2 17M16 7h6v6" />);
export const Home = make('Home', <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />);
export const Layers = make('Layers', <path d="m12 2 10 5-10 5L2 7zM2 17l10 5 10-5M2 12l10 5 10-5" />);
export const Menu = make('Menu', <path d="M4 6h16M4 12h16M4 18h16" />);
export const Target = make('Target', <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></>);
export const GitBranch = make('GitBranch', <><circle cx="6" cy="5" r="2" /><circle cx="6" cy="19" r="2" /><circle cx="18" cy="7" r="2" /><path d="M6 7v10M18 9a6 6 0 0 1-6 6H6" /></>);
