import { useState, useEffect, createContext, useContext, ReactNode } from 'react';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

type NotificationType = 'success' | 'error' | 'info';

interface Notification {
  id: number;
  type: NotificationType;
  message: string;
}

interface NotificationContextType {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const NotificationContext = createContext<NotificationContextType | null>(null);

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const addNotification = (type: NotificationType, message: string) => {
    const id = Date.now();
    setNotifications((prev) => [...prev, { id, type, message }]);

    setTimeout(() => {
      setNotifications((prev) => prev.filter((n) => n.id !== id));
    }, 3000);
  };

  const value = {
    success: (message: string) => addNotification('success', message),
    error: (message: string) => addNotification('error', message),
    info: (message: string) => addNotification('info', message),
  };

  const icons = {
    success: CheckCircle2,
    error: AlertCircle,
    info: Info,
  };

  const colors = {
    success: 'bg-green-50 border-green-200 text-green-800',
    error: 'bg-red-50 border-red-200 text-red-800',
    info: 'bg-blue-50 border-blue-200 text-blue-800',
  };

  return (
    <NotificationContext.Provider value={value}>
      {children}
      <div className="fixed top-4 right-4 z-50 space-y-2 max-w-md">
        {notifications.map((notif) => {
          const Icon = icons[notif.type];
          return (
            <div
              key={notif.id}
              className={`${colors[notif.type]} border px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 animate-in slide-in-from-right`}
            >
              <Icon className="h-5 w-5 flex-shrink-0" />
              <span className="flex-1">{notif.message}</span>
              <button
                onClick={() =>
                  setNotifications((prev) => prev.filter((n) => n.id !== notif.id))
                }
                className="hover:opacity-70"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </NotificationContext.Provider>
  );
}

export function useNotification() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error('useNotification must be used within NotificationProvider');
  }
  return context;
}
