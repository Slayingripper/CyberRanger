import React, { useEffect, useRef, useState } from 'react';
import RFB from '@novnc/novnc/core/rfb';
import { Clipboard, ClipboardCheck, X } from 'lucide-react';

export default function VNCConsole({ host, port, vmName, onClose }) {
  const screenRef = useRef(null);
  const [status, setStatus] = useState('Connecting...');
  const rfbRef = useRef(null);
  const [clipboardText, setClipboardText] = useState('');
  const [showClipboard, setShowClipboard] = useState(false);
  const [pasteFlash, setPasteFlash] = useState(false);

  const sendTextToVM = (text) => {
    if (!rfbRef.current || !text) return;
    
    if (rfbRef.current.capabilities?.clipboard) {
      try {
        rfbRef.current.clipboardPasteFrom(text);
        return true;
      } catch (e) {
        console.warn('clipboardPasteFrom failed, trying key fallback:', e);
      }
    }
    
    const charCodes = [];
    for (let i = 0; i < text.length; i++) {
      charCodes.push(text.charCodeAt(i));
    }
    
    if (charCodes.length > 0) {
      rfbRef.current.focus();
      const sendKeyDownUp = (code) => {
        rfbRef.current.sendKey(code, null, true);
        rfbRef.current.sendKey(code, null, false);
      };
      charCodes.forEach((code) => sendKeyDownUp(code));
      return true;
    }
    return false;
  };

  const handlePasteToVM = () => {
    if (clipboardText) {
      const success = sendTextToVM(clipboardText);
      if (success) {
        setPasteFlash(true);
        setTimeout(() => setPasteFlash(false), 1000);
      }
    }
  };

  const handlePasteFromBrowser = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text && rfbRef.current) {
        setClipboardText(text);
        sendTextToVM(text);
        setPasteFlash(true);
        setTimeout(() => setPasteFlash(false), 1000);
      }
    } catch {
      setShowClipboard(true);
    }
  };

  useEffect(() => {
    if (!screenRef.current) return;

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const hostname = window.location.hostname;
    const url = `${protocol}://${hostname}:8001/api/ws/vnc/${port}`;
    
    try {
        const rfb = new RFB(screenRef.current, url, { shared: true });

        rfb.addEventListener("connect",  () => setStatus("Connected"));
        rfb.addEventListener("disconnect", (e) => {
            setStatus("Disconnected");
        });
        rfb.addEventListener("securityfailure", (e) => {
            setStatus("Security Failure");
            console.error("VNC Security Failure", e);
        });
        
        rfb.addEventListener("clipboard", (e) => {
            const text = e.detail.text;
            if (text) {
                setClipboardText(text);
                setShowClipboard(true);
            }
        });
        
        rfb.scaleViewport = true;
        rfb.resizeSession = false;

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
      <div className="bg-gray-900 text-gray-100 p-3 flex justify-between items-center border-b border-gray-700">
        <div className="flex items-center gap-4">
            <h2 className="font-bold text-lg">Console: {vmName}</h2>
            <span className={`text-xs px-2 py-1 rounded ${status === 'Connected' ? 'bg-green-900 text-green-300' : 'bg-yellow-900 text-yellow-300'}`}>
                {status}
            </span>
        </div>
        <div className="flex gap-2">
            {status === 'Connected' && (
              <>
                <button
                    onClick={handlePasteFromBrowser}
                    className={`p-2 rounded hover:bg-gray-700 transition-colors ${pasteFlash ? 'text-green-400' : 'text-gray-300'}`}
                    title="Paste from clipboard"
                >
                    {pasteFlash ? <ClipboardCheck size={18} /> : <Clipboard size={18} />}
                </button>
                <button
                    onClick={() => setShowClipboard(!showClipboard)}
                    className={`px-3 py-1 rounded text-sm transition-colors ${
                        showClipboard ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'
                    }`}
                    title="Toggle clipboard panel"
                >
                    Clipboard
                </button>
              </>
            )}
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

      {showClipboard && status === 'Connected' && (
        <div className="bg-gray-900 px-3 py-2 border-b border-gray-700">
          <div className="flex gap-2 items-end">
            <textarea
              value={clipboardText}
              onChange={(e) => setClipboardText(e.target.value)}
              placeholder="Type or paste text here, then click Send to VM..."
              className="flex-1 bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white placeholder-gray-500 resize-none focus:border-blue-500 outline-none"
              rows={2}
            />
            <button
              onClick={handlePasteToVM}
              disabled={!clipboardText}
              className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white px-3 py-2 rounded text-sm whitespace-nowrap"
            >
              Send to VM
            </button>
            <button
              onClick={() => setShowClipboard(false)}
              className="p-2 text-gray-400 hover:text-white rounded hover:bg-gray-700"
            >
              <X size={18} />
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-hidden bg-background relative" ref={screenRef}>
        {status !== 'Connected' && (
          <div className="absolute inset-0 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <p className="mb-2">{status}</p>
              {status === 'Connecting...' && <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto"></div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
