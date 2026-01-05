import React, { useEffect, useRef, useState } from 'react';
import RFB from '@novnc/novnc/core/rfb';

const VNCViewer = ({ url, password, viewOnly = false }) => {
    const screenRef = useRef(null);
    const rfbRef = useRef(null);
    const [status, setStatus] = useState('disconnected');

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
        <div className="w-full h-[600px] bg-black relative rounded overflow-hidden border border-border">
            <div ref={screenRef} className="w-full h-full" />
            {status !== 'connected' && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/80 text-white z-10">
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
