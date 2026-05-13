import { useRef, useMemo, useEffect, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float, MeshDistortMaterial, Environment, Stars } from '@react-three/drei';
import * as THREE from 'three';

/**
 * BackgroundScene — demoted to ambient-only cinematic backdrop.
 * - Brand-aligned colors (refined indigo / cyan, not raw #7C3AED / amber)
 * - Slower motion, smaller geometry, less compositing cost
 * - Pauses on non-generate tabs (no frameloop work)
 * - Returns null when prefers-reduced-motion: reduce
 */

const COLOR_IDLE   = '#7C5CFF';
const COLOR_ACTIVE = '#4DD0E1';
const COLOR_PARTICLE_IDLE   = '#9B85FF';
const COLOR_PARTICLE_ACTIVE = '#4DD0E1';

function DistortedSphere({ isGenerating }) {
  const ref = useRef();
  useFrame((state) => {
    if (!ref.current) return;
    const t = state.clock.getElapsedTime();
    const speed = isGenerating ? 1.4 : 0.3; // calmer than before
    ref.current.rotation.x = Math.cos(t / 5) / 2 * speed;
    ref.current.rotation.y = Math.sin(t / 5) / 2 * speed;
    ref.current.rotation.z = Math.sin(t / 2) / 2 * speed;
    const pulse = isGenerating ? 1 + Math.sin(t * 3) * 0.03 : 1;
    ref.current.scale.setScalar(pulse);
  });

  return (
    <Float
      speed={isGenerating ? 2.5 : 1.4}
      rotationIntensity={isGenerating ? 1.2 : 0.6}
      floatIntensity={isGenerating ? 2.5 : 1.2}
    >
      <mesh ref={ref} scale={1.15}>
        <icosahedronGeometry args={[1, 12]} />
        <MeshDistortMaterial
          color={isGenerating ? COLOR_ACTIVE : COLOR_IDLE}
          envMapIntensity={0.9}
          clearcoat={0.7}
          clearcoatRoughness={0}
          roughness={0.15}
          metalness={0.75}
          distort={isGenerating ? 0.45 : 0.25}
          speed={isGenerating ? 3.5 : 1.4}
        />
      </mesh>
    </Float>
  );
}

function ParticleField({ isGenerating }) {
  const count = 180;
  const meshRef = useRef();
  const lightRef = useRef();

  const [positions, scales] = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const scales = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      positions[i * 3]     = (Math.random() - 0.5) * 22;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 22;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 22;
      scales[i] = Math.random();
    }
    return [positions, scales];
  }, [count]);

  useFrame((state) => {
    const t = state.clock.getElapsedTime();
    const speed = isGenerating ? 0.25 : 0.06;
    if (meshRef.current) {
      meshRef.current.rotation.y = t * speed;
      meshRef.current.rotation.x = Math.sin(t * 0.08) * speed;
    }
    if (lightRef.current) {
      lightRef.current.intensity = isGenerating ? 1.4 + Math.sin(t * 3) * 0.4 : 0.4;
    }
  });

  const color = isGenerating ? COLOR_PARTICLE_ACTIVE : COLOR_PARTICLE_IDLE;
  return (
    <group>
      <pointLight ref={lightRef} position={[0, 0, 0]} distance={12} color={color} />
      <points ref={meshRef}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" count={count} array={positions} itemSize={3} />
          <bufferAttribute attach="attributes-scale"    count={count} array={scales}    itemSize={1} />
        </bufferGeometry>
        <pointsMaterial
          size={0.07}
          color={color}
          transparent
          opacity={0.45}
          sizeAttenuation
          blending={THREE.AdditiveBlending}
        />
      </points>
    </group>
  );
}

function Rig({ children }) {
  const groupRef = useRef();
  useFrame((state) => {
    if (!groupRef.current) return;
    const targetX = (state.pointer.x * Math.PI) / 14;
    const targetY = (state.pointer.y * Math.PI) / 14;
    groupRef.current.rotation.y = THREE.MathUtils.lerp(groupRef.current.rotation.y, targetX, 0.035);
    groupRef.current.rotation.x = THREE.MathUtils.lerp(groupRef.current.rotation.x, -targetY, 0.035);
  });
  return <group ref={groupRef}>{children}</group>;
}

/**
 * @param {object} props
 * @param {boolean} props.isGenerating
 * @param {boolean} [props.active=true] — when false, the scene is unmounted entirely (no GPU cost).
 */
export default function BackgroundScene({ isGenerating, active = true }) {
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mq.matches);
    const onChange = (e) => setReducedMotion(e.matches);
    mq.addEventListener?.('change', onChange);
    return () => mq.removeEventListener?.('change', onChange);
  }, []);

  if (reducedMotion || !active) return null;

  return (
    <div id="canvas-container" aria-hidden>
      <Canvas
        camera={{ position: [0, 0, 9], fov: 42 }}
        dpr={typeof window !== 'undefined' && window.devicePixelRatio > 1 ? 1.25 : 1}
        gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
        frameloop={isGenerating ? 'always' : 'demand'}
      >
        <color attach="background" args={['#0A0A0F']} />
        <ambientLight intensity={0.18} />
        <directionalLight position={[10, 10, 5]} intensity={0.85} color="#ffffff" />
        <directionalLight position={[-10, -10, -5]} intensity={0.35} color={COLOR_IDLE} />

        <Rig>
          <Stars
            radius={120}
            depth={60}
            count={1500}
            factor={3}
            saturation={0}
            fade
            speed={isGenerating ? 1 : 0.25}
          />
          <DistortedSphere isGenerating={isGenerating} />
          <ParticleField isGenerating={isGenerating} />
        </Rig>

        <Environment preset="city" />
      </Canvas>
    </div>
  );
}
