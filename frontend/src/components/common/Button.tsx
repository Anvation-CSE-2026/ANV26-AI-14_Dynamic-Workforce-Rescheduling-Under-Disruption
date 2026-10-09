import React from 'react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'destructive' | 'ghost' | 'action';
  size?: 'sm' | 'md' | 'lg';
  icon?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'secondary',
  size = 'md',
  icon,
  className = '',
  disabled,
  ...props
}) => {
  const base = 'inline-flex items-center justify-center font-medium transition-colors select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap rounded shrink-0';

  const sizeClasses = {
    sm: 'text-xs h-7 px-2.5 gap-1.5',
    md: 'text-xs h-8 px-3 gap-1.5',
    lg: 'text-sm h-9 px-4 gap-2',
  }[size];

  const variantClasses = {
    primary: 'bg-slate-900 text-white hover:bg-slate-800 shadow-xs border border-transparent',
    action: 'bg-blue-600 text-white hover:bg-blue-700 shadow-xs border border-transparent',
    secondary: 'bg-white text-slate-800 hover:bg-slate-100 border border-slate-200 shadow-2xs',
    outline: 'bg-transparent text-slate-700 hover:bg-slate-100 border border-slate-300',
    destructive: 'bg-white text-rose-600 border border-rose-200 hover:bg-rose-50 hover:border-rose-300',
    ghost: 'bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900 border-transparent',
  }[variant];

  return (
    <button
      className={`${base} ${sizeClasses} ${variantClasses} ${className}`}
      disabled={disabled}
      {...props}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      <span>{children}</span>
    </button>
  );
};
