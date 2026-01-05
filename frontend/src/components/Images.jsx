import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Upload, Download, File, HardDrive } from 'lucide-react';

const API_URL = 'http://localhost:8001/api';

export default function Images() {
  const [images, setImages] = useState([]);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [downloadUrl, setDownloadUrl] = useState('');
  const [downloadName, setDownloadName] = useState('');
  const [activeDownloads, setActiveDownloads] = useState({});

  useEffect(() => {
    fetchImages();
  }, []);

  useEffect(() => {
    const timer = setTimeout(async () => {
      const activeTaskIds = Object.keys(activeDownloads).filter(id => 
        activeDownloads[id].status !== 'completed' && activeDownloads[id].status !== 'failed'
      );
      
      if (activeTaskIds.length === 0) return;

      const updates = {};
      for (const id of activeTaskIds) {
        try {
          const res = await axios.get(`${API_URL}/images/download/${id}`);
          updates[id] = res.data;
          if (res.data.status === 'completed') fetchImages();
        } catch (e) {
          console.error(e);
        }
      }
      
      if (Object.keys(updates).length > 0) {
        setActiveDownloads(prev => {
          const next = { ...prev };
          for (const [id, data] of Object.entries(updates)) {
            next[id] = { ...next[id], ...data };
          }
          return next;
        });
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [activeDownloads]);

  const fetchImages = async () => {
    try {
      const res = await axios.get(`${API_URL}/images`);
      setImages(res.data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    setUploadProgress(0);
    try {
      await axios.post(`${API_URL}/images/upload`, formData, {
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          setUploadProgress(percentCompleted);
        }
      });
      fetchImages();
    } catch (e) {
      alert('Upload failed');
    } finally {
      setUploadProgress(null);
    }
  };

  const handleDownload = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.post(`${API_URL}/images/download`, {
        url: downloadUrl,
        filename: downloadName
      });
      const { task_id } = res.data;
      setActiveDownloads(prev => ({
        ...prev,
        [task_id]: { filename: downloadName, progress: 0, status: 'pending' }
      }));
      setDownloadUrl('');
      setDownloadName('');
    } catch (e) {
      alert('Download request failed');
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Upload Card */}
        <div className="bg-surface p-6 rounded-xl border border-border">
          <h3 className="text-xl font-bold mb-4 flex items-center gap-2 text-primary">
            <Upload size={20} /> Upload ISO/Image
          </h3>
          <div className="flex items-center justify-center w-full">
            <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-border border-dashed rounded-lg cursor-pointer hover:bg-surfaceHover">
              <div className="flex flex-col items-center justify-center pt-5 pb-6">
                <p className="mb-2 text-sm text-secondary">
                  <span className="font-semibold">Click to upload</span> or drag and drop
                </p>
              </div>
              <input type="file" className="hidden" onChange={handleUpload} disabled={uploadProgress !== null} />
            </label>
          </div>
          {uploadProgress !== null && (
            <div className="mt-4">
               <div className="flex justify-between mb-1">
                  <span className="text-sm text-accent">Uploading...</span>
                  <span className="text-sm text-accent">{uploadProgress}%</span>
               </div>
               <div className="w-full bg-surfaceHover rounded-full h-2.5">
                  <div className="bg-accent h-2.5 rounded-full" style={{ width: `${uploadProgress}%` }}></div>
               </div>
            </div>
          )}
        </div>

        {/* Download Card */}
        <div className="bg-surface p-6 rounded-xl border border-border">
          <h3 className="text-xl font-bold mb-4 flex items-center gap-2 text-primary">
            <Download size={20} /> Download from URL
          </h3>
          <form onSubmit={handleDownload} className="space-y-4">
            <input
              type="text"
              placeholder="Image URL (e.g. https://.../kali.iso)"
              className="w-full bg-background border border-border rounded p-2 text-primary"
              value={downloadUrl}
              onChange={(e) => setDownloadUrl(e.target.value)}
              required
            />
            <input
              type="text"
              placeholder="Filename (e.g. kali.iso)"
              className="w-full bg-background border border-border rounded p-2 text-primary"
              value={downloadName}
              onChange={(e) => setDownloadName(e.target.value)}
              required
            />
            <button type="submit" className="w-full bg-accent hover:bg-accentHover text-primary py-2 rounded">
              Start Download
            </button>
          </form>
          
          <div className="mt-4 pt-4 border-t border-border">
            <p className="text-sm text-secondary mb-2">Quick Presets:</p>
            <div className="flex flex-wrap gap-2">
              <button 
                onClick={() => {
                  setDownloadUrl('https://cdimage.kali.org/kali-2023.4/kali-linux-2023.4-installer-amd64.iso');
                  setDownloadName('kali-linux-2023.4.iso');
                }}
                className="text-xs bg-surfaceHover hover:bg-border px-2 py-1 rounded text-primary"
              >
                Kali Linux
              </button>
              <button 
                onClick={() => {
                  setDownloadUrl('https://releases.ubuntu.com/22.04.3/ubuntu-22.04.3-live-server-amd64.iso');
                  setDownloadName('ubuntu-22.04-server.iso');
                }}
                className="text-xs bg-surfaceHover hover:bg-border px-2 py-1 rounded text-primary"
              >
                Ubuntu Server
              </button>
              <button 
                onClick={() => {
                  setDownloadUrl('https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-standard-3.19.1-x86_64.iso');
                  setDownloadName('alpine-3.19.iso');
                }}
                className="text-xs bg-surfaceHover hover:bg-border px-2 py-1 rounded text-primary"
              >
                Alpine (Lightweight)
              </button>
              <button 
                onClick={() => {
                  setDownloadUrl('https://deb.parrot.sh/parrot/iso/6.0/Parrot-security-6.0_amd64.iso');
                  setDownloadName('parrot-security-6.0.iso');
                }}
                className="text-xs bg-surfaceHover hover:bg-border px-2 py-1 rounded text-primary"
              >
                Parrot OS
              </button>
              <button 
                onClick={() => {
                  setDownloadUrl('https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-12.5.0-amd64-netinst.iso');
                  setDownloadName('debian-12.5.0-netinst.iso');
                }}
                className="text-xs bg-surfaceHover hover:bg-border px-2 py-1 rounded text-primary"
              >
                Debian 12
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Active Downloads */}
      {Object.keys(activeDownloads).length > 0 && (
        <div className="bg-surface rounded-xl border border-border overflow-hidden p-4">
          <h3 className="text-lg font-bold mb-4 text-primary">Active Downloads</h3>
          <div className="space-y-4">
            {Object.entries(activeDownloads).map(([id, task]) => (
              <div key={id} className="bg-background p-3 rounded border border-border">
                <div className="flex justify-between mb-1">
                  <span className="font-medium text-primary">{task.filename}</span>
                  <span className={`text-sm ${task.status === 'failed' ? 'text-red-400' : 'text-accent'}`}>
                    {task.status} {task.progress > 0 && `(${task.progress}%)`}
                  </span>
                </div>
                <div className="w-full bg-surfaceHover rounded-full h-2.5">
                  <div 
                    className={`h-2.5 rounded-full ${task.status === 'failed' ? 'bg-red-600' : 'bg-accent'}`} 
                    style={{ width: `${task.progress}%` }}
                  ></div>
                </div>
                {task.error && <p className="text-red-400 text-xs mt-1">{task.error}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Image List */}
      <div className="bg-surface rounded-xl border border-border overflow-hidden">
        <div className="p-4 border-b border-border">
          <h3 className="text-lg font-bold text-primary">Available Images</h3>
        </div>
        <table className="w-full text-left">
          <thead className="bg-background text-secondary">
            <tr>
              <th className="p-4">Name</th>
              <th className="p-4">Size</th>
              <th className="p-4">Path</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {images.map((img) => (
              <tr key={img.name} className="hover:bg-surfaceHover">
                <td className="p-4 flex items-center gap-2 text-primary">
                  <File size={16} className="text-accent" />
                  {img.name}
                </td>
                <td className="p-4 text-primary">{(img.size / (1024 * 1024)).toFixed(2)} MB</td>
                <td className="p-4 text-secondary text-sm font-mono">{img.host_path}</td>
              </tr>
            ))}
            {images.length === 0 && (
              <tr>
                <td colSpan="3" className="p-8 text-center text-secondary">No images found</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
