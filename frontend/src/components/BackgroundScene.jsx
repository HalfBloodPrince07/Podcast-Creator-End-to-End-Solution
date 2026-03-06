import React, { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float, MeshDistortMaterial, Environment, Stars } from '@react-three/drei';
import * as THREE from 'three';

// A single floating geometric object that distorts and rotates
function DistortedSphere({ isGenerating }) {
    const sphereRef = useRef();

    // Animation loop
    useFrame((state) => {
        const t = state.clock.getElapsedTime();
        // Rotate slowly normally, spin faster when generating
        const speed = isGenerating ? 2.5 : 0.5;
        sphereRef.current.rotation.x = Math.cos(t / 4) / 2 * speed;
        sphereRef.current.rotation.y = Math.sin(t / 4) / 2 * speed;
        sphereRef.current.rotation.z = Math.sin(t / 1.5) / 2 * speed;

        // Scale pulse when generating
        const scaleMultiplier = isGenerating ? 1 + Math.sin(t * 4) * 0.05 : 1;
        sphereRef.current.scale.setScalar(scaleMultiplier);
    });

    // Dynamic colors based on generation state
    const color = isGenerating ? "#F59E0B" : "#7C3AED"; // Accent-warm vs Primary

    return (
        <Float speed={isGenerating ? 4 : 2} rotationIntensity={isGenerating ? 2 : 1} floatIntensity={isGenerating ? 4 : 2}>
            <mesh ref={sphereRef} scale={1.5}>
                <icosahedronGeometry args={[1, 15]} />
                <MeshDistortMaterial
                    color={color}
                    envMapIntensity={1}
                    clearcoat={0.8}
                    clearcoatRoughness={0}
                    roughness={0.1}
                    metalness={0.8}
                    distort={isGenerating ? 0.6 : 0.3}
                    speed={isGenerating ? 6 : 2}
                />
            </mesh>
        </Float>
    );
}

// Background particles that move
function ParticleField({ isGenerating }) {
    const count = 300;
    const meshRef = useRef();
    const lightRef = useRef();

    const [positions, scales] = useMemo(() => {
        const positions = new Float32Array(count * 3);
        const scales = new Float32Array(count);
        for (let i = 0; i < count; i++) {
            positions[i * 3] = (Math.random() - 0.5) * 20;
            positions[i * 3 + 1] = (Math.random() - 0.5) * 20;
            positions[i * 3 + 2] = (Math.random() - 0.5) * 20;
            scales[i] = Math.random();
        }
        return [positions, scales];
    }, [count]);

    useFrame((state) => {
        const t = state.clock.getElapsedTime();
        const speed = isGenerating ? 0.5 : 0.1;

        // Slowly rotate the entire particle field
        if (meshRef.current) {
            meshRef.current.rotation.y = t * speed;
            meshRef.current.rotation.x = Math.sin(t * 0.1) * speed;
        }

        // Pulsing light
        if (lightRef.current) {
            lightRef.current.intensity = isGenerating ? 2 + Math.sin(t * 5) : 0.5;
        }
    });

    const particleColor = isGenerating ? "#06B6D4" : "#A78BFA";

    return (
        <group>
            <pointLight ref={lightRef} position={[0, 0, 0]} distance={10} color={particleColor} />
            <points ref={meshRef}>
                <bufferGeometry>
                    <bufferAttribute
                        attach="attributes-position"
                        count={count}
                        array={positions}
                        itemSize={3}
                    />
                    <bufferAttribute
                        attach="attributes-scale"
                        count={count}
                        array={scales}
                        itemSize={1}
                    />
                </bufferGeometry>
                <pointsMaterial
                    size={0.1}
                    color={particleColor}
                    transparent
                    opacity={0.6}
                    sizeAttenuation
                    blending={THREE.AdditiveBlending}
                />
            </points>
        </group>
    );
}

// Interactivity wrapper to gently move camera with mouse
function Rig({ children }) {
    const groupRef = useRef();
    useFrame((state) => {
        // Smoothly interpolate group rotation based on mouse position
        const targetX = (state.pointer.x * Math.PI) / 10;
        const targetY = (state.pointer.y * Math.PI) / 10;

        groupRef.current.rotation.y = THREE.MathUtils.lerp(groupRef.current.rotation.y, targetX, 0.05);
        groupRef.current.rotation.x = THREE.MathUtils.lerp(groupRef.current.rotation.x, -targetY, 0.05);
    });

    return <group ref={groupRef}>{children}</group>;
}

export default function BackgroundScene({ isGenerating }) {
    return (
        <div id="canvas-container">
            <Canvas
                camera={{ position: [0, 0, 8], fov: 45 }}
                dpr={window.devicePixelRatio > 1 ? 1.5 : 1} // Limit pixel ratio for performance
                gl={{ alpha: true, antialias: true, powerPreference: "high-performance" }}
                frameloop="always" // Keep running to allow continuous animations
            >
                <color attach="background" args={["#050505"]} />
                <ambientLight intensity={0.2} />
                <directionalLight position={[10, 10, 5]} intensity={1} color="#ffffff" />
                <directionalLight position={[-10, -10, -5]} intensity={0.5} color="#7C3AED" />

                <Rig>
                    <Stars radius={100} depth={50} count={3000} factor={4} saturation={0} fade speed={isGenerating ? 2 : 0.5} />
                    <DistortedSphere isGenerating={isGenerating} />
                    <ParticleField isGenerating={isGenerating} />
                </Rig>

                <Environment preset="city" />
            </Canvas>
        </div>
    );
}
