/* Sparse SfM point cloud viewer: three.js Points with vertex colors.
   Loads points3D.ply (directly) or points3D.bin (converted server-side). */
import * as THREE from "three";
import { OrbitControls } from "/vendor/three_addons/OrbitControls.js";
import { parsePlyHeader, extractPoints } from "/ply_parse.js";

const params = new URLSearchParams(location.search);
const run = params.get("run") || "";

const titleEl = document.getElementById("title");
const metaEl = document.getElementById("meta");
const progressBar = document.querySelector("#progress > div");
const errorEl = document.getElementById("error");
const sizeSlider = document.getElementById("ptsize");

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.style.display = "block";
}

function fmtBytes(n) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(i ? 1 : 0) + " " + units[i];
}

async function loadWithProgress(url, onProgress) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const total = parseInt(res.headers.get("content-length"), 10);
  const reader = res.body.getReader();
  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    if (typeof onProgress === "function" && total) onProgress(loaded / total);
  }
  const out = new Uint8Array(loaded);
  let pos = 0;
  for (const c of chunks) { out.set(c, pos); pos += c.length; }
  return out.buffer;
}

async function main() {
  titleEl.textContent = run + " — sparse SfM";

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0f1117);
  const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.001, 5000);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(devicePixelRatio);
  document.body.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  let points = null;
  sizeSlider.addEventListener("input", () => {
    if (points) points.material.size = parseFloat(sizeSlider.value);
  });
  addEventListener("resize", () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  let meta = "";
  try {
    const buffer = await loadWithProgress(`/api/outputs/${encodeURIComponent(run)}/sfm`, (p) => {
      progressBar.style.width = `${Math.min(100, Math.round(p * 100))}%`;
    });
    setTimeout(() => { progressBar.style.width = "0"; }, 600);

    const header = parsePlyHeader(buffer);
    if (header.isAscii) throw new Error("ASCII PLY is not supported; expected binary.");
    const { positions, colors, vertexCount } = extractPoints(buffer, header);

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    if (colors) geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.computeBoundingSphere();

    points = new THREE.Points(geometry, new THREE.PointsMaterial({
      size: parseFloat(sizeSlider.value),
      vertexColors: true,
      sizeAttenuation: true,
    }));
    scene.add(points);

    const center = geometry.boundingSphere.center;
    const radius = geometry.boundingSphere.radius || 1;
    camera.position.set(center.x + radius * 1.5, center.y + radius * 1.5, center.z + radius * 1.5);
    controls.target.copy(center);
    meta = vertexCount.toLocaleString() + " points";
  } catch (e) {
    showError("Failed to load sparse point cloud: " + e.message);
    meta = "load failed";
  } finally {
    metaEl.textContent = meta;
  }

  const frame = () => {
    requestAnimationFrame(frame);
    controls.update();
    renderer.render(scene, camera);
  };
  frame();
}

main();
