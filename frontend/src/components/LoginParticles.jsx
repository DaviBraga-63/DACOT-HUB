import { useEffect, useRef } from "react";

const TEXT = "DACOT";
const TWO_PI = Math.PI * 2;

export function advanceParticle(particle, pointer, radius, elapsed = 1) {
  if (pointer) {
    let dx = particle.x - pointer.x;
    const dy = particle.y - pointer.y;
    const distance = Math.hypot(dx, dy);
    if (distance < radius) {
      if (distance < 1) dx = 1;
      const safeDistance = Math.max(1, distance);
      const force = (1 - distance / radius) * 17 * elapsed;
      particle.vx += (dx / safeDistance) * force;
      particle.vy += (dy / safeDistance) * force;
    }
  }

  particle.vx += (particle.originX - particle.x) * 0.075 * elapsed;
  particle.vy += (particle.originY - particle.y) * 0.075 * elapsed;
  const damping = Math.pow(0.84, elapsed);
  particle.vx *= damping;
  particle.vy *= damping;
  particle.x += particle.vx * elapsed;
  particle.y += particle.vy * elapsed;
  if (!pointer && Math.abs(particle.x - particle.originX) < 0.03
      && Math.abs(particle.y - particle.originY) < 0.03
      && Math.abs(particle.vx) < 0.03 && Math.abs(particle.vy) < 0.03) {
    particle.x = particle.originX;
    particle.y = particle.originY;
    particle.vx = 0;
    particle.vy = 0;
  }
}

function makeParticles(width, height, mobile) {
  const mask = document.createElement("canvas");
  mask.width = width;
  mask.height = height;
  const context = mask.getContext("2d", { willReadFrequently: true });
  if (!context) return [];

  const fontSize = Math.min(width * (mobile ? 0.29 : 0.235), height * 0.42, 290);
  context.font = `900 ${fontSize}px Arial, sans-serif`;
  context.fillStyle = "#fff";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(TEXT, width / 2, height / 2);
  const pixels = context.getImageData(0, 0, width, height).data;
  let spacing = mobile ? 10 : 6;
  const maxParticles = mobile ? 1300 : 4800;
  let particles;
  do {
    particles = [];
    for (let y = 0; y < height; y += spacing) {
      for (let x = 0; x < width; x += spacing) {
        if (pixels[(y * width + x) * 4 + 3] <= 128) continue;
        particles.push({ x, y, originX: x, originY: y, vx: 0, vy: 0 });
      }
    }
    spacing += 1;
  } while (particles.length > maxParticles);
  return particles;
}

export default function LoginParticles() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d", { alpha: false });
    if (!canvas || !context) return undefined;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let particles = [];
    let pointer = null;
    let frame = 0;
    let lastTime = 0;
    let width = 0;
    let height = 0;
    let mobile = false;
    let active = true;

    const draw = () => {
      context.fillStyle = "#090909";
      context.fillRect(0, 0, width, height);
      context.fillStyle = "#503520";
      const size = mobile ? 1.25 : 1.5;
      context.beginPath();
      for (const particle of particles) {
        context.moveTo(particle.x + size, particle.y);
        context.arc(particle.x, particle.y, size, 0, TWO_PI);
      }
      context.fill();
    };

    const animate = (time) => {
      const elapsed = Math.min(2, Math.max(0.5, (time - (lastTime || time - 16.7)) / 16.7));
      lastTime = time;
      const radius = mobile ? 65 : 135;
      for (const particle of particles) advanceParticle(particle, pointer, radius, elapsed);
      draw();
      frame = window.requestAnimationFrame(animate);
    };

    const restart = () => {
      window.cancelAnimationFrame(frame);
      lastTime = 0;
      if (reducedMotion.matches) {
        for (const particle of particles) {
          particle.x = particle.originX;
          particle.y = particle.originY;
          particle.vx = 0;
          particle.vy = 0;
        }
        draw();
      } else frame = window.requestAnimationFrame(animate);
    };

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      const nextWidth = Math.max(1, Math.round(bounds.width));
      const nextHeight = Math.max(1, Math.round(bounds.height));
      if (width === nextWidth && height === nextHeight) return;
      width = nextWidth;
      height = nextHeight;
      mobile = width < 640 || window.matchMedia("(pointer: coarse)").matches;
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      particles = makeParticles(width, height, mobile);
      pointer = null;
      restart();
    };

    const move = (event) => {
      if (reducedMotion.matches || event.pointerType === "touch") return;
      const bounds = canvas.getBoundingClientRect();
      pointer = event.clientX >= bounds.left && event.clientX <= bounds.right
        && event.clientY >= bounds.top && event.clientY <= bounds.bottom
        ? { x: event.clientX - bounds.left, y: event.clientY - bounds.top } : null;
    };
    const leave = () => { pointer = null; };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(canvas);
    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pointermove", move, { passive: true });
    document.documentElement.addEventListener("pointerleave", leave);
    window.addEventListener("blur", leave);
    reducedMotion.addEventListener?.("change", restart);
    resize();
    document.fonts?.ready?.then(() => { if (active) { particles = makeParticles(width, height, mobile); restart(); } });

    return () => {
      active = false;
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", move);
      document.documentElement.removeEventListener("pointerleave", leave);
      window.removeEventListener("blur", leave);
      reducedMotion.removeEventListener?.("change", restart);
    };
  }, []);

  return <canvas ref={canvasRef} className="dh-login-particles" aria-hidden="true" />;
}
