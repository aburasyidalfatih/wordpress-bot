import { useSiteContext } from '@/contexts/SiteContext';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Bot, Plus, ArrowUp, Compass, Sparkles } from 'lucide-react';
import { Link } from 'react-router-dom';

interface EmptyStateProps {
  title?: string;
  description?: string;
}

export default function EmptyState({ title, description }: EmptyStateProps) {
  const { sites } = useSiteContext();

  const noSites = sites.length === 0;

  return (
    <div className="flex items-center justify-center min-h-[450px] p-6 animate-in fade-in slide-in-from-bottom-6 duration-500">
      <Card className="max-w-md w-full border-dashed border-2 border-border/60 shadow-lg hover:shadow-xl hover:border-primary/40 transition-all duration-300 bg-gradient-to-b from-card to-secondary/10">
        <CardContent className="pt-10 pb-8 px-6 text-center flex flex-col items-center">
          
          {noSites ? (
            /* Scenario A: No sites added yet */
            <>
              <div className="relative mb-6">
                <div className="absolute inset-0 bg-primary/10 rounded-full blur-xl animate-pulse"></div>
                <div className="relative p-4 rounded-full bg-primary/10 border border-primary/20 text-primary">
                  <Bot className="h-12 w-12" />
                </div>
                <div className="absolute -bottom-1 -right-1 p-1.5 rounded-full bg-indigo-500 text-white shadow-md border border-background">
                  <Sparkles className="h-3.5 w-3.5" />
                </div>
              </div>
              
              <h3 className="text-xl font-bold tracking-tight text-foreground">
                {title || 'Selamat Datang di AutoWP'}
              </h3>
              <p className="text-sm text-muted-foreground mt-2 max-w-sm">
                {description || 'Otomatisasi konten Anda dengan cerdas. Silakan tambahkan website WordPress Anda terlebih dahulu untuk memulai penulisan berbasis AI.'}
              </p>
              
              <Link 
                to="/sites" 
                className={buttonVariants({
                  variant: 'default',
                  size: 'lg',
                  className: "mt-8 gap-2 shadow-lg shadow-primary/20 hover:shadow-primary/30 transition-all scale-100 hover:scale-[1.02] active:scale-[0.98]"
                })}
              >
                <Plus className="h-4 w-4" />
                Tambah Website Pertama Anda
              </Link>
            </>

          ) : (
            /* Scenario B: Sites exist but none is selected */
            <>
              <div className="relative mb-6">
                <div className="absolute inset-0 bg-indigo-500/10 rounded-full blur-xl animate-pulse"></div>
                <div className="relative p-4 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-600 dark:text-indigo-400">
                  <Compass className="h-12 w-12 animate-spin duration-10000" />
                </div>
                <div className="absolute -top-2 -right-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-white shadow-md animate-bounce">
                  <ArrowUp className="h-3 w-3" />
                </div>
              </div>
              
              <h3 className="text-xl font-bold tracking-tight text-foreground">
                {title || 'Pilih Website Anda'}
              </h3>
              <p className="text-sm text-muted-foreground mt-2 max-w-sm">
                {description || 'Satu langkah lagi! Silakan pilih salah satu website Anda dari menu dropdown di sudut kanan atas untuk melihat analitik dan mengelola konten.'}
              </p>
              
              <div className="mt-8 flex items-center gap-2 text-xs font-semibold text-primary bg-primary/5 border border-primary/20 rounded-full px-4 py-2 animate-pulse">
                <ArrowUp className="h-3.5 w-3.5" />
                Pilih site di sudut kanan atas
              </div>
            </>
          )}
          
        </CardContent>
      </Card>
    </div>
  );
}
