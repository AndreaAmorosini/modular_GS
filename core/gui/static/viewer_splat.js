/* Splat viewer: renders a gaussian splat PLY from an output run. */
import * as SPLAT from "/vendor/gsplat/dist/index.es.js";

const params = new URLSearchParams(location.search);
const run = params.get("run") || "";

const titleEl = document.getElementById("title");
const metaEl = document.getElementById("meta");
const variantsEl = document.getElementById("variants");
const progressBar = document.querySelector("#progress > div");
const errorEl = document.getElementById("error");

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.style.display = "block";
}

function fmtBytes(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(i ? 1 : 0) + " " + units[i];
}

let activeVariant = null;

async function loadVariant(v, scene, camera, renderer) {
  progressBar.style.width = "0";
  const url = `/api/outputs/${encodeURIComponent(run)}/splat?path=${encodeURIComponent(v.path)}`
    + (v.format === "splat" ? "&compact=1" : "&compact=0");
  const onProgress = (p) => {
    if (typeof p === "number") progressBar.style.width = `${Math.min(100, Math.round(p * 100))}%`;
  };
  scene.reset();
  const obj = v.format === "splat"
    ? await SPLAT.Loader.LoadAsync(url, scene, onProgress)
    : await SPLAT.PLYLoader.LoadAsync(url, scene, onProgress);
  const count = obj && obj.data && (obj.data.splatCount ?? obj.data.vertexCount);
  const fmtLabel = v.format === "splat" ? "compact .splat" : "full PLY";
  if (typeof count === "number") {
    metaEl.textContent = v.label + " — " + count.toLocaleString() + " splats (" + fmtBytes(v.size) + ", " + fmtLabel + ")";
  }
  setTimeout(() => { progressBar.style.width = "0"; }, 600);
}

async function main() {
  titleEl.textContent = run;

  const scene = new SPLAT.Scene();
  const camera = new SPLAT.Camera();
  const renderer = new SPLAT.WebGLRenderer();
  const controls = new SPLAT.OrbitControls(camera, renderer.canvas);

  let variants = [];
  try {
    variants = (await fetch(`/api/outputs/${encodeURIComponent(run)}/variants`).then((r) => r.json())).variants;
  } catch (e) {
    showError("Failed to load PLY variants: " + e.message);
    return;
  }
  if (!variants.length) {
    showError("No gaussian splat PLY found for this run.");
    return;
  }

  metaEl.textContent = variants[0].label + " — " + fmtBytes(variants[0].size);

  // variant buttons
  for (const v of variants) {
    const btn = document.createElement("button");
    btn.textContent = v.label;
    btn.title = fmtBytes(v.size);
    btn.dataset.id = v.id;
    btn.addEventListener("click", async () => {
      if (btn.dataset.id === (variantsEl.dataset.active || "")) return;
      variantsEl.dataset.active = btn.dataset.id;
      variantsEl.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
      metaEl.textContent = v.label + " — " + fmtBytes(v.size);
      try {
        await loadVariant(v, scene, camera, renderer);
      } catch (e) {
        showError("Load failed: " + e.message);
      }
    });
    variantsEl.append(btn);
  }
  variantsEl.dataset.active = variants[0].id;
  variantsEl.querySelector("button").classList.add("active");

  const frame = () => {
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);

  try {
    await loadVariant(variants[0], scene, camera, renderer);
  } catch (e) {
    showError("Load failed: " + e.message);
  }
}

main();
