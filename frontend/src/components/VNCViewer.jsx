import React, { useEffect, useRef, useState } from 'react';
import RFB from '@novnc/novnc/core/rfb';
import { Maximize, Minimize } from 'lucide-react';

const VNCViewer = ({ url, password, viewOnly = false }) => {
    const containerRef = useRef(null);
    const screenRef = useRef(null);
    const rfbRef = useRef(null);
    const [status, setStatus] = useState('disconnected');
    const [isFullscreen, setIsFullscreen] = useState(false);

    const toggleFullscreen = () => {
        if (!document.fullscreenElement) {
            containerRef.current?.requestFullscreen().catch(err => {
                console.error(`Error attempting to enable full-screen mode: ${err.message} (${err.name})`);
            });
        } else {
            document.exitFullscreen();
        }
    };

    useEffect(() => {
        const handleFullscreenChange = () => {
            setIsFullscreen(!!document.fullscreenElement);
        };
        document.addEventListener('fullscreenchange', handleFullscreenChange);
        return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
    }, []);

    useEffect(() => {
        if (!url || !screenRef.current) return;

        // Cleanup previous connection
        if (rfbRef.current) {
            rfbRef.current.disconnect();
        }

        const connect = () => {
            try {
                setStatus('connecting');
                // RFB(target, url, options)
                const rfb = new RFB(screenRef.current, url, {
                    credentials: { password: password }
                });

                rfb.viewOnly = viewOnly;
                rfb.scaleViewport = true;
                rfb.resizeSession = true;

                rfb.addEventListener("connect", () => {
                    setStatus('connected');
                });

                rfb.addEventListener("disconnect", (e) => {
                    setStatus('disconnected');
                    console.log("VNC Disconnected", e);
                });

                rfb.addEventListener("securityfailure", (e) => {
                    setStatus('error');
                    console.error("VNC Security Failure", e);
                });

                rfbRef.current = rfb;
            } catch (e) {
                console.error("VNC Connection error:", e);
                setStatus('error');
            }
        };

        // Small delay to ensure DOM is ready
        const timer = setTimeout(connect, 100);

        return () => {
            clearTimeout(timer);
            if (rfbRef.current) {
                rfbRef.current.disconnect();
            }
        };
    }, [url, password, viewOnly]);

    return (
        <div 
            ref={containerRef}
            className={`w-full bg-black relative rounded overflow-hidden border border-border group ${isFullscreen ? 'h-screen flex items-center justify-center' : 'h-[600px]'}`}
        >
            <div className="absolute top-2 right-2 z-20 opacity-0 group-hover:opacity-100 transition-opacity">
                <button 
                    onClick={toggleFullscreen} 
                    className="bg-gray-800/80 text-white p-2 rounded hover:bg-gray-700/80 backdrop-blur-sm"
                    title={isFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
                >
                    {isFullscreen ? <Minimize size={20}/> : <Maximize size={20}/>}
                </button>
            </div>

            <div ref={screenRef} className="w-full h-full" />
            {status !== 'connected' && (
                <div className="absolute inset-0 flex items-center justify-center bg-background/80 text-primary z-10">
                    <div className="text-center">
                        <div className="mb-2 font-bold text-xl">
                            {status === 'connecting' ? 'Connecting to VM...' : 'Disconnected'}
                        </div>
                        {status === 'error' && <div className="text-red-500">Connection Failed</div>}
                    </div>
                </div>
            )}
        </div>
    );
};

export default VNCViewer;
