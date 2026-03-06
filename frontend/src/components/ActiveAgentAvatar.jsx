import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Search,
    PenTool,
    ShieldCheck,
    Music,
    Mic,
    Layers,
    Sparkles,
    Moon,
    CheckCircle,
    Activity
} from 'lucide-react';

export default function ActiveAgentAvatar({ currentStage }) {
    // Determine what to show based on currentStage string
    let agentConfig = {
        id: 'idle',
        label: 'AGENTS IDLE',
        icon: Moon,
        color: '#3b82f6', // blue-500
        animation: {
            animate: { y: [0, -5, 0], opacity: [0.5, 1, 0.5] },
            transition: { repeat: Infinity, duration: 3, ease: 'easeInOut' }
        }
    };

    if (currentStage?.includes('Refining Topic')) {
        agentConfig = {
            id: 'topic_refine',
            label: 'REFINER',
            icon: Sparkles,
            color: '#d946ef', // fuchsia-500
            animation: {
                animate: { scale: [1, 1.2, 1], rotate: [0, 10, -10, 0] },
                transition: { repeat: Infinity, duration: 2 }
            }
        };
    } else if (currentStage?.includes('Researching')) {
        agentConfig = {
            id: 'search',
            label: 'SEARCHER',
            icon: Search,
            color: '#0ea5e9', // sky-500
            animation: {
                animate: { x: [-5, 5, -5] },
                transition: { repeat: Infinity, duration: 1.5, ease: 'easeInOut' }
            }
        };
    } else if (currentStage?.includes('Drafting Script')) {
        agentConfig = {
            id: 'write',
            label: 'WRITER',
            icon: PenTool,
            color: '#10b981', // emerald-500
            animation: {
                animate: { rotate: [-15, 15, -15], y: [0, -2, 0] },
                transition: { repeat: Infinity, duration: 1 }
            }
        };
    } else if (currentStage?.includes('Fact Checking')) {
        agentConfig = {
            id: 'fact_check',
            label: 'CHECKER',
            icon: ShieldCheck,
            color: '#f59e0b', // amber-500
            animation: {
                animate: { scale: [0.95, 1.05, 0.95], opacity: [0.8, 1, 0.8] },
                transition: { repeat: Infinity, duration: 2 }
            }
        };
    } else if (currentStage?.includes('Audio Design')) {
        agentConfig = {
            id: 'audio_design',
            label: 'AUDIO_DSGN',
            icon: Music,
            color: '#ec4899', // pink-500
            animation: {
                animate: { y: [0, -5, 3, -2, 0] },
                transition: { repeat: Infinity, duration: 1.2 }
            }
        };
    } else if (currentStage?.includes('Generating Audio')) {
        agentConfig = {
            id: 'tts',
            label: 'TTS_ENGINE',
            icon: Mic,
            color: '#8b5cf6', // violet-500
            animation: {
                animate: { scale: [1, 1.15, 1] },
                transition: { repeat: Infinity, duration: 0.8 }
            }
        };
    } else if (currentStage?.includes('Assembling')) {
        agentConfig = {
            id: 'assemble',
            label: 'ASSEMBLER',
            icon: Layers,
            color: '#f97316', // orange-500
            animation: {
                animate: { rotate: [0, 90, 180, 270, 360] },
                transition: { repeat: Infinity, duration: 3, ease: 'linear' }
            }
        };
    } else if (currentStage?.includes('Starting')) {
        agentConfig = {
            id: 'starting',
            label: 'BOOTING...',
            icon: Activity,
            color: '#64748b', // slate-500
            animation: {
                animate: { opacity: [0.3, 1, 0.3] },
                transition: { repeat: Infinity, duration: 1 }
            }
        };
    } else if (currentStage?.includes('Complete')) {
        agentConfig = {
            id: 'complete',
            label: 'DONE',
            icon: CheckCircle,
            color: '#14b8a6', // teal-500
            animation: {
                animate: { scale: [1, 1.1, 1] },
                transition: { repeat: Infinity, duration: 2 }
            }
        };
    }

    const Icon = agentConfig.icon;

    return (
        <div
            className="led-screen-container"
            style={{
                width: '100px',
                height: '90px',
                backgroundColor: '#0f172a', /* slate-900 */
                borderRadius: '12px',
                border: '4px solid #1e293b', /* slate-800 */
                boxShadow: 'inset 0 0 15px rgba(0,0,0,0.8), 0 0 10px rgba(0,0,0,0.3)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '0.5rem',
                overflow: 'hidden',
                position: 'relative'
            }}
        >
            {/* Scanline effect layer */}
            <div
                style={{
                    position: 'absolute',
                    top: 0, left: 0, right: 0, bottom: 0,
                    background: 'linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06))',
                    backgroundSize: '100% 4px, 6px 100%',
                    pointerEvents: 'none',
                    zIndex: 10,
                    opacity: 0.6
                }}
            />

            <AnimatePresence mode="popLayout">
                <motion.div
                    key={agentConfig.id}
                    initial={{ opacity: 0, y: 15, scale: 0.8 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -15, scale: 0.8 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                    style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: '0.4rem',
                        zIndex: 5
                    }}
                >
                    <motion.div
                        {...agentConfig.animation}
                        style={{
                            color: agentConfig.color,
                            filter: `drop-shadow(0 0 8px ${agentConfig.color})`, // Glowing effect
                            marginTop: '0.2rem'
                        }}
                    >
                        <Icon size={28} strokeWidth={2.5} />
                    </motion.div>
                    <span
                        style={{
                            color: agentConfig.color,
                            fontFamily: 'monospace',
                            fontSize: '0.65rem',
                            fontWeight: 'bold',
                            textAlign: 'center',
                            textShadow: `0 0 5px ${agentConfig.color}`,
                            letterSpacing: '0.05em'
                        }}
                    >
                        {agentConfig.label}
                    </span>
                </motion.div>
            </AnimatePresence>
        </div>
    );
}
