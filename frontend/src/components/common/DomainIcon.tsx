import React from 'react';
import { HeartPulse, Factory, GraduationCap, Cpu, Truck, Building2 } from './icons';

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = { HeartPulse, Factory, GraduationCap, Cpu, Truck };

export const DomainIcon = ({ name, className = 'w-5 h-5' }: { name?: string; className?: string }) => {
  const I = (name && ICONS[name]) || Building2;
  return <I className={className} />;
};
