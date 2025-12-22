import React, { useEffect, useRef, useState } from 'react';
import RFB from '@novnc/novnc/core/rfb';

export default function VNCConsole({ host, port, vmName, onClose }) {
  const screenRef = useRef(null);
  const [status, setStatus] = useState('Connecting...');
  const rfbRef = useRef(null);

  useEffect(() => {
    if (!screenRef.current) return;

    // Construct WebSocket URL
    // If host is localhost, use window.location.hostname to support remote access if needed
    const targetHost = host === 'localhost' ? window.location.hostname : host;
    const url = `ws://${targetHost}:${port}`;
    
    console.log(`Connecting to VNC at ${url}`);

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
      <div className="bg-gray-800 text-white p-3 flex justify-between items-center border-b border-gray-700">
        <div className="flex items-center gap-4">
            <h2 className="font-bold text-lg">Console: {vmName}</h2>
            <span className={`text-xs px-2 py-1 rounded ${status === 'Connected' ? 'bg-green-900 text-green-300' : 'bg-yellow-900 text-yellow-300'}`}>
                {status}
            </span>
        </div>
        <div className="flex gap-2">
            <button 
                onClick={() => rfbRef.current?.sendCtrlAltDel()} 
                className="bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded text-sm"
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
      <div className="flex-1 overflow-hidden bg-gray-900 relative" ref={screenRef}>
        {/* Canvas injected here */}
      </div>
    </div>
  );
}
