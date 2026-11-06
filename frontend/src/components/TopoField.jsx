import { useEffect, useRef } from "react";

const VERTEX_SHADER = `
  attribute vec2 a_position;

  void main() {
    gl_Position = vec4(a_position, 0.0, 1.0);
  }
`;

// Self-contained topographic field: no image, canvas library, or external script.
const FRAGMENT_SHADER = `
  precision highp float;

  uniform vec2 u_resolution;
  uniform float u_time;
  uniform float u_motion;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);

    return mix(
      mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
      mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
      u.y
    );
  }

  float field(vec2 p) {
    float value = 0.0;
    float amplitude = 0.55;
    mat2 rotation = mat2(0.82, -0.57, 0.57, 0.82);

    for (int octave = 0; octave < 5; octave++) {
      value += amplitude * noise(p);
      p = rotation * p * 2.03 + vec2(4.7, 1.9);
      amplitude *= 0.5;
    }

    return value;
  }

  float contour(float elevation, float density, float width) {
    float distanceToLine = abs(fract(elevation * density) - 0.5);
    return 1.0 - smoothstep(width, width * 2.25, distanceToLine);
  }

  void main() {
    vec2 resolution = max(u_resolution, vec2(1.0));
    vec2 uv = gl_FragCoord.xy / resolution;
    vec2 centered = uv - 0.5;
    centered.x *= resolution.x / resolution.y;

    float time = u_time * u_motion;
    vec2 drift = vec2(time * 0.018, -time * 0.012);
    float elevation = field(centered * 1.72 + drift);
    elevation += 0.115 * sin(centered.x * 2.8 + time * 0.22);
    elevation += 0.085 * cos(centered.y * 3.1 - time * 0.17);

    float fineContours = contour(elevation, 15.0, 0.0105);
    float majorContours = contour(elevation, 5.0, 0.0125);

    vec2 grid = abs(fract((centered + vec2(8.0)) * 14.0) - 0.5);
    float gridLine = 1.0 - smoothstep(0.485, 0.5, max(grid.x, grid.y));
    float vignette = 1.0 - smoothstep(0.18, 0.9, length(centered));

    vec3 color = vec3(0.0);
    color += vec3(0.30) * fineContours * (0.42 + vignette * 0.22);
    color += vec3(0.56) * majorContours * (0.19 + vignette * 0.16);
    color += vec3(0.16) * gridLine * 0.13;
    color += vec3(0.022) * vignette;

    gl_FragColor = vec4(color, 1.0);
  }
`;

function createShader(gl, type, source) {
  const shader = gl.createShader(type);
  if (!shader) return null;

  gl.shaderSource(shader, source);
  gl.compileShader(shader);

  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }

  return shader;
}

function createProgram(gl) {
  const vertexShader = createShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
  const fragmentShader = createShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  if (!vertexShader || !fragmentShader) return null;

  const program = gl.createProgram();
  if (!program) return null;

  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  gl.deleteShader(vertexShader);
  gl.deleteShader(fragmentShader);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program);
    return null;
  }

  return program;
}

export default function TopoField() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const gl = canvas.getContext("webgl", {
      alpha: false,
      antialias: true,
      powerPreference: "low-power",
    });
    if (!gl) return undefined;

    const program = createProgram(gl);
    if (!program) return undefined;

    const positionBuffer = gl.createBuffer();
    if (!positionBuffer) {
      gl.deleteProgram(program);
      return undefined;
    }

    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );

    const positionLocation = gl.getAttribLocation(program, "a_position");
    const resolutionLocation = gl.getUniformLocation(program, "u_resolution");
    const timeLocation = gl.getUniformLocation(program, "u_time");
    const motionLocation = gl.getUniformLocation(program, "u_motion");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frameId = 0;
    let isActive = true;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
      const width = Math.max(1, Math.round(rect.width * pixelRatio));
      const height = Math.max(1, Math.round(rect.height * pixelRatio));

      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }

      gl.viewport(0, 0, width, height);
    };

    const render = (milliseconds = 0) => {
      if (!isActive) return;

      resize();
      gl.useProgram(program);
      gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
      gl.enableVertexAttribArray(positionLocation);
      gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
      gl.uniform2f(resolutionLocation, canvas.width, canvas.height);
      gl.uniform1f(timeLocation, milliseconds * 0.001);
      gl.uniform1f(motionLocation, reducedMotion.matches ? 0.0 : 1.0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      if (!reducedMotion.matches) frameId = window.requestAnimationFrame(render);
    };

    const restart = () => {
      window.cancelAnimationFrame(frameId);
      render(0);
    };

    const resizeObserver = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(restart);
    resizeObserver?.observe(canvas);
    window.addEventListener("resize", restart, { passive: true });
    reducedMotion.addEventListener?.("change", restart);
    render(0);

    return () => {
      isActive = false;
      window.cancelAnimationFrame(frameId);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", restart);
      reducedMotion.removeEventListener?.("change", restart);
      gl.deleteBuffer(positionBuffer);
      gl.deleteProgram(program);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="dh-topo-field"
      aria-hidden="true"
      data-testid="login-topo-field"
    />
  );
}
