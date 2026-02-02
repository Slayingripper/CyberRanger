import React, { useMemo } from 'react';
import ReactFlow, { Background, Controls } from 'reactflow';
import 'reactflow/dist/style.css';
import CustomNode from './CustomNode';
import Modal from './Modal';

const nodeTypes = {
  custom: CustomNode,
};

const TopologyViewer = ({ topology, onClose }) => {
    const nodes = useMemo(() => {
        if (!topology || !topology.nodes) return [];
        return topology.nodes.map((n, idx) => ({
            id: n.id,
            type: 'custom', // Force type to 'custom' used in nodeTypes
            position: n.position || { x: 50 + (idx * 150), y: 50 + (idx % 3) * 100 },
            data: { 
                label: n.label, 
                image: n.config?.image,
                assets: n.config?.assets,
                ...n.data // spread existing data just in case
            },
            draggable: false,
            selectable: true 
        }));
    }, [topology]);
    
    const edges = useMemo(() => {
        if (!topology || !topology.edges) return [];
        return topology.edges.map((e, idx) => ({
            ...e,
            id: e.id || `e-${e.source}-${e.target}-${idx}`,
            animated: true,
            style: { stroke: '#4b5563' }
        }));
    }, [topology]);

    return (
        <Modal isOpen={true} onClose={onClose} title={`Topology: ${topology?.scenario?.name || 'Custom Deployment'}`} footer={<button onClick={onClose} className="px-4 py-2 bg-surface hover:bg-surfaceHover text-primary rounded">Close</button>} size="xl">
            <div className="h-[600px] w-full bg-background border border-border rounded-lg overflow-hidden relative">
                 <div className="absolute top-2 right-2 z-10 bg-surface/80 p-2 rounded text-xs text-secondary pointer-events-none">
                    Read-only View
                </div>
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={nodeTypes}
                    fitView
                >
                    <Background color="#1f2937" gap={16} />
                    <Controls />
                </ReactFlow>
            </div>
        </Modal>
    );
};

export default TopologyViewer;
