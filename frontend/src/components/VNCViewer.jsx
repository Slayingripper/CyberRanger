import React, { useEffect, useRef, useState } from 'react';
import RFB from '@novnc/novnc/core/rfb';
import { Maximize, Minimize, Clipboard, ClipboardCheck } from 'lucide-react';

const VNCViewer = ({ url, password, viewOnly = false, credentials }) => {
    const containerRef = useRef(null);
    const screenRef = useRef(null);
    const rfbRef = useRef(null);
    const [status, setStatus] = useState('disconnected');
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [clipboardText, setClipboardText] = useState('');
    const [showClipboard, setShowClipboard] = useState(false);
    const [pasteFlash, setPasteFlash] = useState(false);

    const toggleFullscreen = () => {
        if (!document.fullscreenElement) {
            containerRef.current?.requestFullscreen().catch(err => {
                console.error(`Error attempting to enable full-screen mode: ${err.message} (${err.name})`);
            });
        } else {
            document.exitFullscreen();
        }
    };

    const handlePasteToVM = () => {
        if (rfbRef.current && clipboardText) {
            rfbRef.current.clipboardPasteFrom(clipboardText);
            setPasteFlash(true);
            setTimeout(() => setPasteFlash(false), 1000);
        }
    };

    const handlePasteFromBrowser = async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text && rfbRef.current) {
                setClipboardText(text);
                rfbRef.current.clipboardPasteFrom(text);
                setPasteFlash(true);
                setTimeout(() => setPasteFlash(false), 1000);
            }
        } catch {
            setShowClipboard(true);
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

        if (rfbRef.current) {
            rfbRef.current.disconnect();
        }

        const connect = () => {
            try {
                setStatus('connecting');
                const rfb = new RFB(screenRef.current, url, {
                    credentials: { password: password }
                });

                rfb.viewOnly = viewOnly;
                rfb.scaleViewport = true;
                rfb.resizeSession = false;

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
            className={`w-full bg-black relative rounded overflow-hidden border border-border group ${isFullscreen ? 'h-screen flex flex-col' : 'h-[600px] flex flex-col'}`}
        >
            {/* Top toolbar — always visible when connected */}
            {status === 'connected' && (
                <div className="flex items-center justify-between bg-gray-900/95 px-3 py-1.5 text-xs z-20 shrink-0 border-b border-gray-700">
                    <div className="flex items-center gap-3">
                        <span className="flex items-center gap-1.5 text-green-400">
                            <span className="w-2 h-2 rounded-full bg-green-400 inline-block"></span>
                            Connected
                        </span>
                        {credentials?.username && credentials?.password && (
                            <span className="text-blue-300 flex items-center gap-3 ml-2 border-l border-gray-600 pl-3">
                                <span>User: <code className="bg-gray-800 px-1.5 py-0.5 rounded font-mono text-white">{credentials.username}</code></span>
                                <span>Pass: <code className="bg-gray-800 px-1.5 py-0.5 rounded font-mono text-white">{credentials.password}</code></span>
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-1">
                        <button
                            onClick={handlePasteFromBrowser}
                            className={`p-1.5 rounded hover:bg-gray-700/80 transition-colors ${
                                pasteFlash ? 'text-green-400' : 'text-gray-300'
                            }`}
                            title="Paste from clipboard into VM"
                        >
                            {pasteFlash ? <ClipboardCheck size={16} /> : <Clipboard size={16} />}
                        </button>
                        <button
                            onClick={() => setShowClipboard(!showClipboard)}
                            className={`px-2 py-1 rounded text-xs transition-colors ${
                                showClipboard ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700/80'
                            }`}
                            title="Open clipboard panel"
                        >
                            Clipboard
                        </button>
                        <button 
                            onClick={toggleFullscreen} 
                            className="p-1.5 rounded text-gray-300 hover:bg-gray-700/80 transition-colors"
                            title={isFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
                        >
                            {isFullscreen ? <Minimize size={16}/> : <Maximize size={16}/>}
                        </button>
                    </div>
                </div>
            )}

            {/* Clipboard panel */}
            {showClipboard && status === 'connected' && (
                <div className="bg-gray-900/95 px-3 py-2 border-b border-gray-700 z-20 shrink-0">
                    <div className="flex gap-2 items-end">
                        <textarea
                            value={clipboardText}
                            onChange={(e) => setClipboardText(e.target.value)}
                            placeholder="Type or paste text here, then click Send to send it to the VM..."
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
                    </div>
                </div>
            )}

            <div ref={screenRef} className="flex-1 min-h-0" />

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
