import React, { memo } from 'react';
import { Handle, Position } from 'reactflow';
import { Server, Monitor, ShieldAlert, ShieldCheck, Router, Globe, Laptop } from 'lucide-react';

const CustomNode = ({ data, selected }) => {
  const getIcon = () => {
    const img = (data.image || '').toLowerCase();
    const label = (data.label || '').toLowerCase();

    if (img.includes('gateway') || label.includes('gateway') || label.includes('router')) return <Router size={24} className="text-orange-400" />;
    if (img.includes('kali') || label.includes('attacker') || label.includes('red')) return <ShieldAlert size={24} className="text-red-500" />;
    if (img.includes('windows') || label.includes('victim')) return <Monitor size={24} className="text-blue-400" />;
    if (img.includes('ubuntu') || img.includes('server')) return <Server size={24} className="text-green-400" />;
    if (label.includes('internet')) return <Globe size={24} className="text-blue-300" />;
    
    return <Laptop size={24} className="text-secondary" />;
  };

  const getBorderColor = () => {
      if (selected) return 'border-accent ring-2 ring-accent/50';
      return 'border-border';
  };

  return (
    <div className={`px-4 py-3 shadow-lg rounded-lg bg-surface border ${getBorderColor()} min-w-[150px]`}>
      <Handle type="target" position={Position.Top} className="w-3 h-3 bg-secondary" />
      
      <div className="flex items-center gap-3">
        <div className="p-2 bg-background rounded-full border border-border">
            {getIcon()}
        </div>
        <div>
            <div className="text-sm font-bold text-primary">{data.label}</div>
            <div className="text-xs text-secondary">{data.image || 'Unknown Image'}</div>
        </div>
      </div>

      {data.assets && data.assets.length > 0 && (
          <div className="mt-2 pt-2 border-t border-border flex gap-1 flex-wrap">
              {data.assets.map((a, i) => (
                  <span key={i} className="text-[10px] px-1.5 py-0.5 bg-surfaceHover rounded text-secondary truncate max-w-[60px]">
                      {a.value}
                  </span>
              ))}
          </div>
      )}

      <Handle type="source" position={Position.Bottom} className="w-3 h-3 bg-secondary" />
    </div>
  );
};

export default memo(CustomNode);
