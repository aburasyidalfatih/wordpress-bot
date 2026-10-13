import { useState } from 'react';
import { LandingNav } from '@/components/landing/LandingNav';
import { HeroSection } from '@/components/landing/HeroSection';
import { FeaturesSection } from '@/components/landing/FeaturesSection';
import { WorkflowSection } from '@/components/landing/WorkflowSection';
import { PricingSection } from '@/components/landing/PricingSection';
import { LandingFooter } from '@/components/landing/LandingFooter';

export default function Landing() {
  // Only decides which call-to-action links to show; the token is not verified here.
  const [isLoggedIn] = useState(() => !!localStorage.getItem('token'));

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-indigo-500 selection:text-white overflow-x-hidden">
      {/* Decorative background glows */}
      <div className="absolute top-0 left-1/4 -translate-x-1/2 w-[500px] h-[500px] bg-indigo-500/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute top-[20%] right-1/4 translate-x-1/2 w-[600px] h-[600px] bg-violet-500/10 rounded-full blur-[150px] pointer-events-none" />
      <div className="absolute bottom-[20%] left-10 w-[400px] h-[400px] bg-blue-500/5 rounded-full blur-[100px] pointer-events-none" />

      <LandingNav isLoggedIn={isLoggedIn} />
      <HeroSection isLoggedIn={isLoggedIn} />
      <FeaturesSection />
      <WorkflowSection />
      <PricingSection isLoggedIn={isLoggedIn} />
      <LandingFooter isLoggedIn={isLoggedIn} />
    </div>
  );
}
