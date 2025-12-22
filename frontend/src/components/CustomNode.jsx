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
    
    return <Laptop size={24} className="text-gray-400" />;
  };

  const getBorderColor = () => {
      if (selected) return 'border-blue-500 ring-2 ring-blue-500/50';
      return 'border-gray-600';
  };

  return (
    <div className={`px-4 py-3 shadow-lg rounded-lg bg-gray-800 border ${getBorderColor()} min-w-[150px]`}>
      <Handle type="target" position={Position.Top} className="w-3 h-3 bg-gray-400" />
      
      <div className="flex items-center gap-3">
        <div className="p-2 bg-gray-900 rounded-full border border-gray-700">
            {getIcon()}
        </div>
        <div>
            <div className="text-sm font-bold text-gray-200">{data.label}</div>
            <div className="text-xs text-gray-500">{data.image || 'Unknown Image'}</div>
        </div>
      </div>

      {data.assets && data.assets.length > 0 && (
          <div className="mt-2 pt-2 border-t border-gray-700 flex gap-1 flex-wrap">
              {data.assets.map((a, i) => (
                  <span key={i} className="text-[10px] px-1.5 py-0.5 bg-gray-700 rounded text-gray-300 truncate max-w-[60px]">
                      {a.value}
                  </span>
              ))}
          </div>
      )}

      <Handle type="source" position={Position.Bottom} className="w-3 h-3 bg-gray-400" />
    </div>
  );
};

export default memo(CustomNode);
