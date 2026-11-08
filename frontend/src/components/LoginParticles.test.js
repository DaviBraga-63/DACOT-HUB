import { advanceParticle } from "./LoginParticles";

test("cursor disperses a particle and it returns to its exact origin", () => {
  const particle = { x: 0, y: 0, originX: 0, originY: 0, vx: 0, vy: 0 };
  for (let i = 0; i < 12; i += 1) advanceParticle(particle, { x: 10, y: 0 }, 135);
  expect(particle.x).toBeLessThan(-1);
  for (let i = 0; i < 300; i += 1) advanceParticle(particle, null, 135);
  expect(particle.x).toBe(0);
  expect(particle.y).toBe(0);
  expect(particle.vx).toBe(0);
});

test("repulsion remains finite when cursor is on a particle", () => {
  const particle = { x: 20, y: 20, originX: 20, originY: 20, vx: 0, vy: 0 };
  advanceParticle(particle, { x: 20, y: 20 }, 135);
  expect(Number.isFinite(particle.x)).toBe(true);
  expect(Number.isFinite(particle.y)).toBe(true);
});

test("desktop cursor uses the same strong repulsion as Pedidos", () => {
  const particle = { x: 0, y: 0, originX: 0, originY: 0, vx: 0, vy: 0 };
  advanceParticle(particle, { x: 10, y: 0 }, 135);
  expect(particle.x).toBeLessThan(-10);
});
