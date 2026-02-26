import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';
import { Button } from '../ui/button';

interface PageHeaderProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: {
    label: string;
    onClick: () => void;
    icon?: LucideIcon;
  };
}

export function PageHeader({ title, description, icon: Icon, action }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2">
          {Icon && <Icon className="h-8 w-8" />}
          {title}
        </h1>
        {description && <p className="text-muted-foreground mt-1">{description}</p>}
      </div>
      {action && (
        <Button onClick={action.onClick} className="gap-2">
          {action.icon && <action.icon className="h-4 w-4" />}
          {action.label}
        </Button>
      )}
    </div>
  );
}
