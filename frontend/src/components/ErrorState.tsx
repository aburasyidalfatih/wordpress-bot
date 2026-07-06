import { AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from './ui/button';
import { Card, CardContent } from './ui/card';

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({ message, onRetry, className = '' }: ErrorStateProps) {
  return (
    <Card className={`bg-destructive/5 border-destructive/20 ${className}`}>
      <CardContent className="flex flex-col items-center justify-center p-8 text-center space-y-4">
        <div className="bg-destructive/10 p-3 rounded-full">
          <AlertCircle className="w-8 h-8 text-destructive" />
        </div>
        <div className="space-y-1">
          <h3 className="font-semibold text-destructive">Failed to Load Data</h3>
          <p className="text-sm text-muted-foreground max-w-md">{message}</p>
        </div>
        {onRetry && (
          <Button variant="outline" onClick={onRetry} className="mt-2 border-destructive/20 hover:bg-destructive/10 text-foreground">
            <RefreshCw className="w-4 h-4 mr-2" />
            Try Again
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
