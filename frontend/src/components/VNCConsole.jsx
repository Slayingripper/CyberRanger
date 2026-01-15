import React, { useEffect, useRef, useState } from 'react';
import RFB from '@novnc/novnc/core/rfb';

export default function VNCConsole({ host, port, vmName, onClose }) {
  const screenRef = useRef(null);
  const [status, setStatus] = useState('Connecting...');
  const rfbRef = useRef(null);

  useEffect(() => {
    if (!screenRef.current) return;

    // Construct WebSocket URL for Proxy
    // We ignore 'host' (usually localhost) and point to our API proxy
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const hostname = window.location.hostname;
    const url = `${protocol}://${hostname}:8001/api/ws/vnc/${port}`;
    
    console.log(`Connecting to VNC Proxy at ${url}`);

    try {
        const rfb = new RFB(screenRef.current, url);

        rfb.addEventListener("connect",  () => setStatus("Connected"));
        rfb.addEventListener("disconnect", (e) => {
            setStatus("Disconnected");
            console.log("VNC Disconnected", e);
        });
        rfb.addEventListener("securityfailure", (e) => {
            setStatus("Security Failure");
            console.error("VNC Security Failure", e);
        });
        
        rfb.scaleViewport = true;
        rfb.resizeSession = true;

        rfbRef.current = rfb;
    } catch (err) {
        console.error("Failed to initialize RFB", err);
        setStatus("Error initializing VNC");
    }

    return () => {
      if (rfbRef.current) {
        rfbRef.current.disconnect();
      }
    };
  }, [host, port]);

  return (
    <div className="fixed inset-0 z-50 bg-black flex flex-col">
      <div className="bg-surface text-primary p-3 flex justify-between items-center border-b border-border">
        <div className="flex items-center gap-4">
            <h2 className="font-bold text-lg">Console: {vmName}</h2>
            <span className={`text-xs px-2 py-1 rounded ${status === 'Connected' ? 'bg-green-900 text-green-300' : 'bg-yellow-900 text-yellow-300'}`}>
                {status}
            </span>
        </div>
        <div className="flex gap-2">
            <button 
                onClick={() => rfbRef.current?.sendCtrlAltDel()} 
                className="bg-surfaceHover hover:bg-border px-3 py-1 rounded text-sm"
            >
                Send Ctrl-Alt-Del
            </button>
            <button 
                onClick={onClose} 
                className="bg-red-600 hover:bg-red-700 px-4 py-1 rounded text-sm font-bold"
            >
                Close
            </button>
        </div>
      </div>
            <div className="flex-1 overflow-hidden bg-background relative" ref={screenRef}>
        {status !== 'Connected' && (
          <div className="absolute inset-0 flex items-center justify-center text-secondary">
            <div className="text-center">
              <p className="mb-2">{status}</p>
              {status === 'Connecting...' && <div className="animate-spin h-8 w-8 border-4 border-accent border-t-transparent rounded-full mx-auto"></div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
