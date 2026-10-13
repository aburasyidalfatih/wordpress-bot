import { useEffect, useRef } from 'react';

const MAX_PARTICLES = 75;
const CONNECTION_DISTANCE = 110;
const MOUSE_CONNECTION_DISTANCE = 160;
const COLOR = '99, 102, 241';

interface Particle { x: number; y: number; vx: number; vy: number; r: number }

/** Full-window "spider web" particle animation. Attach the returned ref to a <canvas>. */
export function useParticleCanvas() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const mouse = { x: -1000, y: -1000, active: false };
    let animationFrameId: number;
    let particles: Particle[] = [];

    const initParticles = () => {
      particles = Array.from({ length: MAX_PARTICLES }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.7,
        vy: (Math.random() - 0.5) * 0.7,
        r: Math.random() * 1.8 + 0.8,
      }));
    };

    const resizeCanvas = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      initParticles();
    };

    const drawLine = (x1: number, y1: number, x2: number, y2: number, alpha: number, width: number) => {
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.strokeStyle = `rgba(${COLOR}, ${alpha})`;
      ctx.lineWidth = width;
      ctx.stroke();
    };

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;

        // Bounce on boundaries
        if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > canvas.height) p.vy *= -1;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${COLOR}, 0.25)`;
        ctx.fill();

        // Connect with other particles
        for (let j = i + 1; j < particles.length; j++) {
          const p2 = particles[j];
          const dist = Math.hypot(p.x - p2.x, p.y - p2.y);
          if (dist < CONNECTION_DISTANCE) {
            drawLine(p.x, p.y, p2.x, p2.y, (1 - dist / CONNECTION_DISTANCE) * 0.12, 0.7);
          }
        }

        // Connect to the mouse cursor
        if (mouse.active) {
          const dist = Math.hypot(p.x - mouse.x, p.y - mouse.y);
          if (dist < MOUSE_CONNECTION_DISTANCE) {
            drawLine(p.x, p.y, mouse.x, mouse.y, (1 - dist / MOUSE_CONNECTION_DISTANCE) * 0.22, 0.9);
          }
        }
      }

      animationFrameId = requestAnimationFrame(draw);
    };

    const handleMouseMove = (e: MouseEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.active = true;
    };
    const handleMouseLeave = () => { mouse.active = false; };

    window.addEventListener('resize', resizeCanvas);
    window.addEventListener('mousemove', handleMouseMove);
    document.body.addEventListener('mouseleave', handleMouseLeave);

    resizeCanvas();
    draw();

    return () => {
      window.removeEventListener('resize', resizeCanvas);
      window.removeEventListener('mousemove', handleMouseMove);
      document.body.removeEventListener('mouseleave', handleMouseLeave);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return canvasRef;
}
