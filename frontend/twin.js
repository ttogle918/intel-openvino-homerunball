// 3D 디지털 트윈: three.js + urdf-loader로 SO-101 URDF를 그린다. app.js가 import('./twin.js')로 불러온다.
// 관절값은 라디안 6개 (서버 twin.to_radians). 마우스: 왼쪽 드래그 회전, 휠 확대, 오른쪽 드래그 이동.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from 'urdf-loader';

export const JOINTS = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'];

export function createTwin(host, urdfUrl) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });   // WebGL이 없으면 여기서 예외 → 호출 쪽 "3D 없음"
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x2a1a10);
  scene.add(new THREE.HemisphereLight(0xfff4e0, 0x3a2314, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 2.0);
  sun.position.set(1, 2, 1.5);
  scene.add(sun);
  scene.add(new THREE.GridHelper(0.8, 16, 0x8a6a4a, 0x4a3424));

  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 20);
  camera.position.set(0.45, 0.4, 0.55);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.12, 0);
  controls.enableDamping = true;
  controls.update();

  let robot = null;
  let raf = 0;
  let disposed = false;
  const resize = () => {
    const w = host.clientWidth || 1;
    const h = host.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  resize();
  const loop = () => {
    raf = requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  };
  loop();

  const api = {
    setJoints(q) {
      if (!robot || !q) return;
      JOINTS.forEach((name, i) => {
        if (Number.isFinite(q[i])) robot.setJointValue(name, q[i]);
      });
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };

  return new Promise((resolve, reject) => {
    const manager = new THREE.LoadingManager();
    manager.onError = (url) => console.warn('3D 파일 로드 실패:', url);
    manager.onLoad = () => {   // URDF와 STL을 모두 받은 뒤 (STL 일부가 실패해도 나머지로 그린다)
      if (!disposed && robot) resolve(api);
    };
    const loader = new URDFLoader(manager);
    loader.load(urdfUrl, (r) => {
      robot = r;
      robot.rotation.x = -Math.PI / 2;   // URDF는 Z가 위, three.js는 Y가 위
      scene.add(robot);
    }, null, (e) => {
      api.dispose();
      reject(e);
    });
  });
}
