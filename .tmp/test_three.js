const three = await import("/run/media/ater/DATA/modular_GS/core/gui/static/vendor/three.module.min.js");
console.log("REVISION:", three.REVISION);
console.log("Points:", typeof three.Points, "| PointsMaterial:", typeof three.PointsMaterial, "| BufferGeometry:", typeof three.BufferGeometry);
const geo = new three.BufferGeometry();
geo.setAttribute("position", new three.BufferAttribute(new Float32Array([0, 0, 0, 1, 1, 1]), 3));
geo.computeBoundingSphere();
console.log("bounding sphere radius:", geo.boundingSphere.radius);
console.log("THREE CHAIN OK");
