import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import ReactFlow, {
  ReactFlowProvider,
  addEdge,
  useNodesState,
  useEdgesState,
  Controls,
  Background,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Play, Plus, Trash2, Upload, FileText, Target, Shield, Flag } from 'lucide-react';
import yaml from 'js-yaml';
import axios from 'axios';
import CustomNode from './CustomNode';
import Modal from './Modal';
import { getApiUrl } from '../lib/api';

const initialNodes = [
  {
    id: '1',
    type: 'custom',
    data: { label: 'Internet Gateway', image: 'gateway', cpu: 1, ram: 512, assets: [] },
    position: { x: 250, y: 5 },
  },
];

const PREDEFINED_TOPOLOGIES = {
    "simple-client-server": {
        scenario: {
            name: 'Simple Client-Server',
            team: 'blue',
            objective: 'Deploy a simple web server and client.',
            difficulty: 'easy'
        },
        nodes: [
            { id: '1', type: 'custom', position: { x: 100, y: 100 }, data: { label: 'Web Server', image: 'ubuntu-20.04', cpu: 2, ram: 2048, assets: [{ type: 'package', value: 'nginx' }] } },
            { id: '2', type: 'custom', position: { x: 400, y: 100 }, data: { label: 'Client', image: 'ubuntu-20.04', cpu: 1, ram: 1024, assets: [{ type: 'package', value: 'curl' }] } }
        ],
        edges: [
            { id: 'e1-2', source: '1', target: '2' }
        ]
    },
    "iot-environment": {
        scenario: {
            name: 'IoT Environment',
            team: 'red',
            objective: 'Deploy an IoT network with MQTT broker and simulated sensors. Configure the MQTT broker and establish sensor connections.',
            difficulty: 'medium',
            sources: {
                "ubuntu-20.04": { "url": "https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img", "filename": "focal-server-cloudimg-amd64.img" }
            }
        },
        nodes: [
            { id: '1', type: 'custom', position: { x: 250, y: 50 }, data: { label: 'IoT Gateway', image: 'ubuntu-20.04', cpu: 2, ram: 2048, assets: [{ type: 'package', value: 'mosquitto mosquitto-clients' }, { type: 'package', value: 'python3-pip' }, { type: 'command', value: 'pip3 install paho-mqtt' }, { type: 'command', value: 'systemctl enable mosquitto' }, { type: 'command', value: 'systemctl start mosquitto' }] }},
            { id: '2', type: 'custom', position: { x: 100, y: 200 }, data: { label: 'Temperature Sensor', image: 'ubuntu-20.04', cpu: 1, ram: 512, assets: [{ type: 'package', value: 'python3-pip' }, { type: 'command', value: 'pip3 install paho-mqtt' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nimport paho.mqtt.client as mqtt\nimport time, random, os, sys\n\nbroker = os.getenv(\"BROKER_IP\", \"192.168.1.10\")\nport = 1883\n\ndef on_connect(c, u, f, rc):\n    print(f\"Connected to {broker}\", flush=True)\n\nc = mqtt.Client()\nc.on_connect = on_connect\nc.connect(broker, port, 60)\nc.loop_start()\n\nwhile True:\n    temp = round(20 + random.uniform(-5, 25), 2)\n    c.publish(\"iot/sensors/temperature\", str(temp))\n    time.sleep(5)\n\' > /opt/sensor_sim.py && chmod +x /opt/sensor_sim.py' }] }},
            { id: '3', type: 'custom', position: { x: 250, y: 200 }, data: { label: 'Motion Sensor', image: 'ubuntu-20.04', cpu: 1, ram: 512, assets: [{ type: 'package', value: 'python3-pip' }, { type: 'command', value: 'pip3 install paho-mqtt' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nimport paho.mqtt.client as mqtt\nimport time, random, os\n\nbroker = os.getenv(\"BROKER_IP\", \"192.168.1.10\")\nc = mqtt.Client()\nc.connect(broker, 1883, 60)\nc.loop_start()\n\nwhile True:\n    motion = random.choice([0, 0, 0, 1])\n    c.publish(\"iot/sensors/motion\", str(motion))\n    time.sleep(3)\n\' > /opt/motion_sim.py && chmod +x /opt/motion_sim.py' }] }},
            { id: '4', type: 'custom', position: { x: 400, y: 200 }, data: { label: 'Light Sensor', image: 'ubuntu-20.04', cpu: 1, ram: 512, assets: [{ type: 'package', value: 'python3-pip' }, { type: 'command', value: 'pip3 install paho-mqtt' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nimport paho.mqtt.client as mqtt\nimport time, random, os\n\nbroker = os.getenv(\"BROKER_IP\", \"192.168.1.10\")\nc = mqtt.Client()\nc.connect(broker, 1883, 60)\nc.loop_start()\n\nwhile True:\n    light = round(random.uniform(0, 1000), 2)\n    c.publish(\"iot/sensors/light\", str(light))\n    time.sleep(4)\n\' > /opt/light_sim.py && chmod +x /opt/light_sim.py' }] }},
            { id: '5', type: 'custom', position: { x: 250, y: 350 }, data: { label: 'Dashboard', image: 'ubuntu-20.04', cpu: 2, ram: 2048, assets: [{ type: 'package', value: 'python3-pip nginx' }, { type: 'command', value: 'pip3 install paho-mqtt flask flask-socketio' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nfrom flask import Flask, render_template_string\nfrom flask_socketio import SocketIO\nimport paho.mqtt.client as mqtt\nimport json, threading, time\n\napp = Flask(__name__)\nsio = SocketIO(app)\n\ndata = {\"temperature\": \"--\", \"motion\": \"--\", \"light\": \"--\"}\nlock = threading.Lock()\n\ndef on_msg(client, userdata, msg):\n    with lock:\n        if \"temperature\" in msg.topic:\n            data[\"temperature\"] = msg.payload.decode()\n        elif \"motion\" in msg.topic:\n            data[\"motion\"] = \"Motion\" if msg.payload.decode() == \"1\" else \"Clear\"\n        elif \"light\" in msg.topic:\n            data[\"light\"] = msg.payload.decode()\n        sio.emit(\"update\", data)\n\ndef mqtt_worker():\n    c = mqtt.Client()\n    c.on_message = on_msg\n    c.connect(os.getenv(\"BROKER_IP\", \"192.168.1.10\"), 1883)\n    c.subscribe(\"iot/sensors/#\")\n    c.loop_forever()\n\nthreading.Thread(target=mqtt_worker, daemon=True).start()\n\nHTML = """<!DOCTYPE html><html><head><title>IoT Dashboard</title>\n<style>body{font-family:Arial;padding:20px;background:#1a1a2e;color:#fff}\n.card{background:#16213e;padding:20px;margin:10px;border-radius:10px;display:inline-block;min-width:200px}\n.value{font-size:32px;color:#00d9ff}</style></head>\n<body><h1>IoT Dashboard</h1>\n<div class="card"><h3>Temperature</h3><div class="value" id="temp">--</div></div>\n<div class="card"><h3>Motion</h3><div class="value" id="motion">--</div></div>\n<div class="card"><h3>Light</h3><div class="value" id="light">--</div></div>\n<script src="//cdn.socket.io/socket.io-3.0.0.min.js"></script>\n<script>var s=io();s.on(\"update\",function(d){document.getElementById(\"temp\").innerHTML=d.temperature+\" C\";document.getElementById(\"motion\").innerHTML=d.motion;document.getElementById(\"light\").innerHTML=d.light+\" lux\";});</script>\n</body></html>"""\n\n@app.route(\"/\")\ndef index():\n    return HTML\n\nif __name__ == \"__main__\":\n    sio.run(app, host=\"0.0.0.0\", port=5000)\n\' > /opt/dashboard.py && chmod +x /opt/dashboard.py' }] }}
        ],
        edges: [
            { id: 'e1-2', source: '1', target: '2' },
            { id: 'e1-3', source: '1', target: '3' },
            { id: 'e1-4', source: '1', target: '4' },
            { id: 'e1-5', source: '1', target: '5' }
        ]
    },
    "pv-solar-plant": {
        scenario: {
            name: 'PV Solar Plant Monitoring',
            team: 'blue',
            objective: 'Deploy a photovoltaic solar plant monitoring system with SCADA, data logger, and real-time dashboard.',
            difficulty: 'medium',
            sources: {
                "ubuntu-20.04": { "url": "https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img", "filename": "focal-server-cloudimg-amd64.img" }
            }
        },
        nodes: [
            { id: '1', type: 'custom', position: { x: 250, y: 50 }, data: { label: 'SCADA Server', image: 'ubuntu-20.04', cpu: 2, ram: 4096, assets: [{ type: 'package', value: 'python3-pip apache2' }, { type: 'command', value: 'pip3 install flask flask-cors' }, { type: 'command', value: 'a2enmod proxy_http && systemctl restart apache2' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nfrom flask import Flask, jsonify\nfrom flask_cors import CORS\nimport time, random\n\napp = Flask(__name__)\nCORS(app)\n\ndef gen_data():\n    hour = time.localtime().tm_hour\n    solar = max(0, min(1000, 500 * (6 <= hour <= 18) * (1 - abs(hour - 12) / 8) + random.uniform(-50, 50)))\n    return {\"voltage\": round(random.uniform(580, 620), 2), \"current\": round(solar / 600, 3),\n            \"power\": round(random.uniform(280, 350), 2), \"temp\": round(25 + solar / 50, 2)}\n\n@app.route(\"/api/pv\")\ndef pv(): return jsonify(gen_data())\n\n@app.route(\"/\")\ndef index():\n    return """<!DOCTYPE html><html><head><title>PV Monitor</title>\n    <style>body{font-family:Arial;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:20px}\n    .card{background:rgba(0,0,0,0.3);padding:20px;margin:10px;border-radius:10px;display:inline-block}\n    h1{text-align:center}</style></head>\n    <body><h1>PV Solar Monitor</h1>\n    <div class="card"><h3>Voltage</h3><div id="v">--</div></div>\n    <div class="card"><h3>Current</h3><div id="c">--</div></div>\n    <div class="card"><h3>Power</h3><div id="p">--</div></div>\n    <div class="card"><h3>Temperature</h3><div id="t">--</div></div>\n    <script>setInterval(()=>{fetch("/api/pv").then(r=>r.json()).then(d=>{\n        document.getElementById("v").innerHTML=d.voltage+\" V\";\n        document.getElementById("c").innerHTML=d.current+\" A\";\n        document.getElementById("p").innerHTML=d.power+\" W\";\n        document.getElementById("t").innerHTML=d.temp+\" C\";});},2000);</script>\n    </body></html>"""\n\nif __name__ == \"__main__\": app.run(host=\"0.0.0.0\", port=5000)\n\' > /opt/scada.py && chmod +x /opt/scada.py' }] }},
            { id: '2', type: 'custom', position: { x: 100, y: 250 }, data: { label: 'Data Logger', image: 'ubuntu-20.04', cpu: 1, ram: 1024, assets: [{ type: 'package', value: 'influxdb telegraf' }, { type: 'command', value: 'systemctl enable influxdb telegraf && systemctl start influxdb' }, { type: 'command', value: 'echo \'#!/bin/bash\nwhile true; do\n  DATA=$(curl -s http://192.168.1.10:5000/api/pv)\n  influx -execute \"INSERT solar power=$(echo $DATA | grep -o \'"\'"\'"power\\":[0-9.]*\'"\'"\' | cut -d: -f2)\"\n  sleep 10\ndone\' > /opt/logger.sh && chmod +x /opt/logger.sh' }] }},
            { id: '3', type: 'custom', position: { x: 400, y: 250 }, data: { label: 'Alert System', image: 'ubuntu-20.04', cpu: 1, ram: 512, assets: [{ type: 'package', value: 'postfix' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nimport time, subprocess, urllib.request, json\n\nwhile True:\n    try:\n        data = json.loads(urllib.request.urlopen(\"http://192.168.1.10:5000/api/pv\", timeout=5).read())\n        if data["power"] < 100:\n            print(f"ALERT: Low power {data[\'power\']}W\")\n    except: pass\n    time.sleep(60)\n\' > /opt/alert.py && chmod +x /opt/alert.py' }] }},
            { id: '4', type: 'custom', position: { x: 250, y: 400 }, data: { label: 'Analytics Server', image: 'ubuntu-20.04', cpu: 2, ram: 2048, assets: [{ type: 'package', value: 'python3-pip grafana' }, { type: 'command', value: 'pip3 install pandas matplotlib requests' }] }}
        ],
        edges: [
            { id: 'e1-2', source: '1', target: '2' },
            { id: 'e1-3', source: '1', target: '3' },
            { id: 'e1-4', source: '1', target: '4' }
        ]
    },
    "iiot-environment": {
        scenario: {
            name: 'IIoT Industrial Environment',
            team: 'red',
            objective: 'Deploy an Industrial IoT environment with PLC simulation, OPC-UA server, and data historian.',
            difficulty: 'hard',
            sources: {
                "ubuntu-20.04": { "url": "https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img", "filename": "focal-server-cloudimg-amd64.img" }
            }
        },
        nodes: [
            { id: '1', type: 'custom', position: { x: 250, y: 50 }, data: { label: 'SCADA/HMI', image: 'ubuntu-20.04', cpu: 2, ram: 4096, assets: [{ type: 'package', value: 'python3-pip nginx' }, { type: 'command', value: 'pip3 install flask flask-socketio' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nfrom flask import Flask, render_template_string\nfrom flask_socketio import SocketIO\nimport random, time, threading\n\napp = Flask(__name__)\nsio = SocketIO(app)\n\nmachines = {\"M1\": {\"temp\": 45, \"speed\": 75}, \"M2\": {\"temp\": 52, \"speed\": 60}}\n\ndef updater():\n    while True:\n        for m in machines.values():\n            m[\"temp\"] = max(30, min(80, m[\"temp\"] + random.uniform(-2, 2)))\n            m[\"speed\"] = max(0, min(100, m[\"speed\"] + random.uniform(-5, 5)))\n        sio.emit(\"data\", machines)\n        time.sleep(1)\n\nthreading.Thread(target=updater, daemon=True).start()\n\nHTML = """<!DOCTYPE html><html><head><title>SCADA HMI</title>\n<style>body{font-family:Arial;background:#1a1a2e;color:#fff;padding:20px}\n.machine{background:#16213e;padding:20px;margin:10px;display:inline-block;border-radius:10px;min-width:200px}\n.alert{color:#ff4444;font-weight:bold}</style></head>\n<body><h1>SCADA HMI</h1>\n<div id="machines"></div>\n<script src="//cdn.socket.io/socket.io-3.0.0.min.js"></script>\n<script>\nvar s=io();\ns.on(\"data\",function(d){\n  var html=\"\";\n  for(var k in d){var m=d[k];\n    html+=\"<div class=machine><h3>\"+k+\"</h3>\";\n    html+=\"<p>Temp: <span>\"+m.temp.toFixed(1)+\" C</span></p>\";\n    html+=\"<p>Speed: <span>\"+m.speed.toFixed(0)+\" %</span></p>\";\n    if(m.temp>70)html+=\"<p class=alert>HIGH TEMP</p>\";\n    html+=\"</div>\";}\n  document.getElementById(\"machines\").innerHTML=html;\n});\n</script></body></html>"""\n\n@app.route(\"/\")\ndef index(): return HTML\nif __name__==\"__main__\": sio.run(app, host=\"0.0.0.0\", port=5000)\n\' > /opt/scada_hmi.py && chmod +x /opt/scada_hmi.py' }] }},
            { id: '2', type: 'custom', position: { x: 100, y: 250 }, data: { label: 'PLC-1', image: 'ubuntu-20.04', cpu: 1, ram: 1024, assets: [{ type: 'package', value: 'python3-pip' }, { type: 'command', value: 'pip3 install pymodbus' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nfrom pymodbus.server.sync import StartTcpServer\nfrom pymodbus.datastore import ModbusSequentialDataBlock\nfrom pymodbus.datastore.context import ModbusServerContext\nimport random, time\n\nstore = ModbusSequentialDataBlock(0, [0]*100)\nctx = ModbusServerContext(slaves={1: store})\n\nwhile True:\n    store.set_values(0, [1, 75, int(random.uniform(450, 550)), int(random.uniform(40, 60))])\n    time.sleep(1)\n\nStartTcpServer(ctx, address=(\"\", 5020))\n\' > /opt/plc_sim.py && chmod +x /opt/plc_sim.py' }] }},
            { id: '3', type: 'custom', position: { x: 400, y: 250 }, data: { label: 'OPC-UA Server', image: 'ubuntu-20.04', cpu: 1, ram: 1024, assets: [{ type: 'package', value: 'python3-pip' }, { type: 'command', value: 'pip3 install opcua-asyncio' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nfrom opcua import Server\nimport asyncio, random\n\nasync def main():\n    s = Server()\n    await s.init()\n    s.set_endpoint(\"opc.tcp://0.0.0.0:4840/\")\n    idx = await s.register_namespace(\"IIoT\")\n    obj = s.get_objects_node()\n    dev = await obj.add_object(idx, \"Devices\")\n    m1 = await dev.add_object(idx, \"Machine1\")\n    await m1.add_variable(idx, \"Temperature\", 45.0)\n    await m1.add_variable(idx, \"Speed\", 75.0)\n    await s.start()\n    while True:\n        await asyncio.sleep(1)\n        v = await (await m1.get_child(str(idx)+\":Temperature\")).get_value()\n        await (await m1.get_child(str(idx)+\":Temperature\")).set_value(max(30, min(80, v + random.uniform(-2, 2))))\n\nasyncio.run(main())\n\' > /opt/opcua_server.py && chmod +x /opt/opcua_server.py' }] }},
            { id: '4', type: 'custom', position: { x: 100, y: 450 }, data: { label: 'Data Historian', image: 'ubuntu-20.04', cpu: 2, ram: 2048, assets: [{ type: 'package', value: 'mariadb-server' }, { type: 'package', value: 'python3-pip' }, { type: 'command', value: 'pip3 install mysql-connector-python' }, { type: 'command', value: 'mysql -e "CREATE DATABASE IF NOT EXISTS historian; CREATE TABLE IF NOT EXISTS historian.sensor_data (id INT AUTO_INCREMENT, ts TIMESTAMP DEFAULT NOW(), machine VARCHAR(50), temp DOUBLE, speed DOUBLE, PRIMARY KEY(id));"' }, { type: 'command', value: 'systemctl enable mariadb && systemctl start mariadb' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nimport mysql.connector, time, random\n\nconn = mysql.connector.connect(host=\"localhost\", user=\"root\", database=\"historian\")\ncur = conn.cursor()\n\nwhile True:\n    for m in [\"M1\", \"M2\"]:\n        cur.execute(\"INSERT INTO sensor_data (machine, temp, speed) VALUES (%s, %s, %s)\", (m, random.uniform(40,70), random.uniform(50,90)))\n    conn.commit()\n    time.sleep(5)\n\' > /opt/historian.py && chmod +x /opt/historian.py' }] }},
            { id: '5', type: 'custom', position: { x: 400, y: 450 }, data: { label: 'MES Server', image: 'ubuntu-20.04', cpu: 2, ram: 2048, assets: [{ type: 'package', value: 'python3-pip postgresql' }, { type: 'command', value: 'pip3 install psycopg2-binary flask' }, { type: 'command', value: 'echo \'#!/usr/bin/env python3\nfrom flask import Flask, jsonify\nfrom flask_cors import CORS\nimport psycopg2, time\n\napp = Flask(__name__)\nCORS(app)\n\ntry:\n    conn = psycopg2.connect(host=\"localhost\", database=\"postgres\", user=\"postgres\", password=\"postgres\")\nexcept:\n    import subprocess\n    subprocess.run([\"service\", \"postgresql\", \"start\"])\n    time.sleep(2)\n    conn = psycopg2.connect(host=\"localhost\", database=\"postgres\", user=\"postgres\", password=\"postgres\")\n\ncur = conn.cursor()\ncur.execute(\"CREATE TABLE IF NOT EXISTS production_orders (id SERIAL, product VARCHAR(50), qty INT, status VARCHAR(20));\")\nconn.commit()\n\n@app.route(\"/api/orders\")\ndef orders():\n    cur.execute(\"SELECT * FROM production_orders\")\n    return jsonify([{\"id\": r[0], \"product\": r[1], \"qty\": r[2]} for r in cur.fetchall()])\n\n@app.route(\"/\")\ndef index(): return \"<h1>MES Server</h1><p>API: /api/orders</p>\"\nif __name__==\"__main__\": app.run(host=\"0.0.0.0\", port=5000)\n\' > /opt/mes.py && chmod +x /opt/mes.py' }] }}
        ],
        edges: [
            { id: 'e1-2', source: '1', target: '2' },
            { id: 'e1-3', source: '1', target: '3' },
            { id: 'e1-4', source: '1', target: '4' },
            { id: 'e1-5', source: '1', target: '5' },
            { id: 'e2-1', source: '2', target: '1' },
            { id: 'e3-1', source: '3', target: '1' }
        ]
    }
};
let id = 0;
const getId = () => `dndnode_${id++}`;

const API_URL = getApiUrl();

const SCENARIO_DEFAULTS = {
    name: 'New Scenario',
    team: 'blue',
    objective: 'Defend the network against incoming attacks.',
    difficulty: 'easy',
    network_prefix: ''
};

const NetworkBuilder = () => {
  const reactFlowWrapper = useRef(null);
    const cacheTimerRef = useRef(null);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [reactFlowInstance, setReactFlowInstance] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [availableImages, setAvailableImages] = useState([]);
    const [runtimeVms, setRuntimeVms] = useState([]);
    const [viewportRestored, setViewportRestored] = useState(false);
        const [scanTarget, setScanTarget] = useState('192.168.1.0/24');
        const [scanBusy, setScanBusy] = useState(false);
        const [scanDryRun, setScanDryRun] = useState(false);
        const [importBusy, setImportBusy] = useState(false);
  
  // Scenario State
  const [scenarioConfig, setScenarioConfig] = useState({
      ...SCENARIO_DEFAULTS
  });
  const [showScenarioSettings, setShowScenarioSettings] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);
    const [deployJobId, setDeployJobId] = useState(null);
    const [deployJob, setDeployJob] = useState(null);
    const [deployJobError, setDeployJobError] = useState(null);
    const [messageModal, setMessageModal] = useState({ isOpen: false, title: '', message: '', type: 'info' });

  const nodeTypes = useMemo(() => ({ custom: CustomNode }), []);

  const formatBytes = (bytes) => {
      const b = Number(bytes || 0);
      if (!Number.isFinite(b) || b <= 0) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB', 'TB'];
      const idx = Math.min(units.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
      const val = b / Math.pow(1024, idx);
      const digits = idx === 0 ? 0 : (val < 10 ? 2 : 1);
      return `${val.toFixed(digits)} ${units[idx]}`;
  };

  const formatSpeed = (bps) => {
      const v = Number(bps || 0);
      if (!Number.isFinite(v) || v <= 0) return null;
      return `${formatBytes(v)}/s`;
  };

  const formatEta = (seconds) => {
      const s = Number(seconds);
      if (!Number.isFinite(s) || s <= 0) return null;
      if (s < 60) return `${Math.round(s)}s`;
      if (s < 3600) return `${Math.round(s / 60)}m`;
      return `${(s / 3600).toFixed(1)}h`;
  };

  const nodeVmInfoMap = useMemo(() => {
      const map = {};
      runtimeVms.forEach(vm => {
          const match = nodes.find(n => vm?.name?.endsWith(`_${n.id}`));
          if (match) {
              map[match.id] = vm;
          }
      });
      return map;
  }, [runtimeVms, nodes]);

  const vmInfoForNode = useCallback((nodeId) => {
      return nodeVmInfoMap[nodeId] || null;
  }, [nodeVmInfoMap]);

  const primaryIp = useCallback((vmInfo) => {
      if (!vmInfo || !vmInfo.interfaces) return null;
      for (const iface of vmInfo.interfaces) {
          if (iface?.ips && iface.ips.length > 0) {
              return iface.ips[0];
          }
      }
      return null;
  }, []);

  const nodeMap = useMemo(() => {
      const map = {};
      nodes.forEach(n => { map[n.id] = n; });
      return map;
  }, [nodes]);

  const vmIpList = useMemo(() => nodes.map(n => {
      const info = nodeVmInfoMap[n.id];
      const ip = primaryIp(info);
      return { id: n.id, label: n.data.label, info, ip };
  }), [nodes, nodeVmInfoMap, primaryIp]);

  const connectionList = useMemo(() => edges.map(e => {
      const src = nodeMap[e.source];
      const dst = nodeMap[e.target];
      return {
          id: e.id,
          source: e.source,
          target: e.target,
          srcLabel: src?.data?.label || e.source,
          dstLabel: dst?.data?.label || e.target,
          srcIp: primaryIp(nodeVmInfoMap[e.source]),
          dstIp: primaryIp(nodeVmInfoMap[e.target])
      };
  }), [edges, nodeMap, nodeVmInfoMap, primaryIp]);

  // Persistence Logic - Load saved topology on mount
  useEffect(() => {
      const saved = localStorage.getItem('networkTopology');
      if (saved) {
          try {
              const { nodes: savedNodes, edges: savedEdges, scenario: savedScenario } = JSON.parse(saved);
              if (Array.isArray(savedNodes)) setNodes(savedNodes);
              if (Array.isArray(savedEdges)) setEdges(savedEdges);
              if (savedScenario) setScenarioConfig(savedScenario);
              return;
          } catch (err) {
              console.error('Failed to load saved topology', err);
          }
      }

      // Fallback to backend cache if local storage is empty/invalid
      (async () => {
          try {
              const res = await axios.get(`${API_URL}/topology/cache`);
              // Backend returns the topology object directly, or wrapped. checking checks.
              const topo = res.data?.topology || res.data;
              if (topo?.nodes || topo?.edges) {
                  const savedNodes = topo.nodes || [];
                  const savedEdges = topo.edges || [];
                  if (Array.isArray(savedNodes)) setNodes(savedNodes);
                  if (Array.isArray(savedEdges)) setEdges(savedEdges);
                  if (topo.scenario) setScenarioConfig(topo.scenario);
              }
          } catch (err) {
              // Ignore if no cached topology exists
          }
      })();
  }, []);

  // Restore viewport when ReactFlow instance is ready
  useEffect(() => {
      if (reactFlowInstance && !viewportRestored) {
          const saved = localStorage.getItem('networkTopology');
          if (saved) {
              try {
                  const { viewport } = JSON.parse(saved);
                  if (viewport) {
                      // Small delay to ensure ReactFlow is fully initialized
                      setTimeout(() => {
                          reactFlowInstance.setViewport(viewport);
                          setViewportRestored(true);
                      }, 100);
                  } else {
                      // No saved viewport, fit the view to show all nodes
                      setTimeout(() => {
                          reactFlowInstance.fitView();
                          setViewportRestored(true);
                      }, 100);
                  }
              } catch (err) {
                  console.error('Failed to restore viewport', err);
                  setViewportRestored(true);
              }
          } else {
              // No saved topology, fit the view
              setTimeout(() => {
                  reactFlowInstance.fitView();
                  setViewportRestored(true);
              }, 100);
          }
      }
  }, [reactFlowInstance, viewportRestored]);

  // Save topology when it changes
  useEffect(() => {
      if (nodes.length > 0 || edges.length > 0) {
          const viewport = reactFlowInstance ? reactFlowInstance.getViewport() : null;
          const topology = { nodes, edges, scenario: scenarioConfig, viewport };
          localStorage.setItem('networkTopology', JSON.stringify(topology));

          if (cacheTimerRef.current) {
              clearTimeout(cacheTimerRef.current);
          }
          cacheTimerRef.current = setTimeout(async () => {
              try {
                  await axios.post(`${API_URL}/topology/cache`, topology);
              } catch (err) {
                  // Best-effort cache; ignore failures
              }
          }, 750);
      }
  }, [nodes, edges, scenarioConfig, reactFlowInstance]);

  const buildTopologyPayload = () => ({
      scenario: scenarioConfig,
      nodes: nodes.map(n => ({
          id: n.id,
          label: n.data.label,
          position: n.position,
          config: {
              image: n.data.image,
              cpu: n.data.cpu,
              ram: n.data.ram,
              assets: n.data.assets,
              automation: n.data.automation || null,
              username: n.data.username || null,
              password: n.data.password || null
          }
      })),
      edges: edges.map(e => ({
          id: e.id,
          source: e.source,
          target: e.target
      }))
  });

  const handleClearTopology = async () => {
      setNodes([]);
      setEdges([]);
      setSelectedNode(null);
      setScenarioConfig({ ...SCENARIO_DEFAULTS });
      localStorage.removeItem('networkTopology');
      localStorage.removeItem('deployJobId');
      setDeployJob(null);
      setDeployJobId(null);
      setDeployJobError(null);
      try {
          await axios.post(`${API_URL}/topology/cache`, {});
      } catch (err) {
          // Best-effort cache clear only.
      }
      setTimeout(() => reactFlowInstance?.fitView(), 50);
      setMessageModal({ isOpen: true, title: 'Cleared', message: 'Topology cleared.', type: 'success' });
  };

  const handleSaveTopology = async () => {
      const topology = buildTopologyPayload();
      const viewport = reactFlowInstance ? reactFlowInstance.getViewport() : null;
      const cachedTopology = { ...topology, viewport };
      localStorage.setItem('networkTopology', JSON.stringify(cachedTopology));
      try {
          await axios.post(`${API_URL}/topology/cache`, cachedTopology);
      } catch (err) {
          // Local save still succeeds even if backend cache fails.
      }

      const yamlPayload = yaml.dump(topology, { noRefs: true });
      const blob = new Blob([yamlPayload], { type: 'text/yaml;charset=utf-8' });
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      const baseName = (scenarioConfig.name || 'topology').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'topology';
      link.href = downloadUrl;
      link.download = `${baseName}.yaml`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);

      setMessageModal({ isOpen: true, title: 'Saved', message: `Topology saved as ${baseName}.yaml`, type: 'success' });
  };

  // Save viewport on page unload/visibility change
  useEffect(() => {
      const saveViewport = () => {
          if (reactFlowInstance) {
              const saved = localStorage.getItem('networkTopology');
              if (saved) {
                  try {
                      const topology = JSON.parse(saved);
                      topology.viewport = reactFlowInstance.getViewport();
                      localStorage.setItem('networkTopology', JSON.stringify(topology));
                  } catch (err) {
                      console.error('Failed to save viewport', err);
                  }
              }
          }
      };

      window.addEventListener('beforeunload', saveViewport);
      window.addEventListener('visibilitychange', saveViewport);
      document.addEventListener('visibilitychange', saveViewport);

      return () => {
          window.removeEventListener('beforeunload', saveViewport);
          window.removeEventListener('visibilitychange', saveViewport);
          document.removeEventListener('visibilitychange', saveViewport);
          saveViewport();
      };
  }, [reactFlowInstance]);

  useEffect(() => {
      const fetchImages = async () => {
          try {
              const res = await axios.get(`${API_URL}/images`);
              setAvailableImages(res.data || []);
          } catch (err) {
              console.error("Failed to fetch images", err);
          }
      };
      fetchImages();
      const timer = setInterval(fetchImages, 30000); // Refresh every 30 seconds (less critical data)
      return () => clearInterval(timer);
  }, []);

  const scanAndImport = async () => {
      if (!scanTarget || scanBusy) return;
      setScanBusy(true);
      try {
          const res = await axios.post(`${API_URL}/range-mapper/scan`, {
              target: scanTarget,
              scenario_name: 'Imported Network',
              dry_run: !!scanDryRun,
          });

          if (res.data?.dry_run) {
              setMessageModal({
                  isOpen: true,
                  title: 'Dry Run',
                  message: `Would scan ${res.data.target} (see console for commands).`,
                  type: 'info'
              });
              return;
          }

          const topo = res.data?.topology;
          if (!topo?.nodes) throw new Error('No topology returned');

          const newNodes = topo.nodes.map(n => ({
              id: n.id,
              type: 'custom',
              position: n.position || { x: 100, y: 100 },
              data: {
                  label: n.label || 'VM',
                  image: n.config?.image || 'ubuntu-20.04',
                  cpu: n.config?.cpu || 1,
                  ram: n.config?.ram || 1024,
                  assets: n.config?.assets || [],
                  automation: n.config?.automation || null,
                  meta: n.meta || null,
              }
          }));
          setNodes(newNodes);

          const newEdges = (topo.edges || []).map((e, idx) => ({
              id: e.id || `e${idx}`,
              source: e.source,
              target: e.target
          }));
          setEdges(newEdges);

          if (topo.scenario) {
              setScenarioConfig({ ...SCENARIO_DEFAULTS, ...(topo.scenario || {}) });
          }

          setMessageModal({ isOpen: true, title: 'Imported', message: `Imported ${newNodes.length} nodes from scan.`, type: 'success' });
      } catch (err) {
          console.error(err);
          const msg = err?.response?.data?.detail || err.message || 'Scan failed';
          setMessageModal({ isOpen: true, title: 'Scan Error', message: msg, type: 'error' });
      } finally {
          setScanBusy(false);
      }
  };

  const importXmlAndConvert = async (file) => {
      if (!file || importBusy) return;
      setImportBusy(true);
      try {
          const form = new FormData();
          form.append('file', file);
          // scenario_name/network_prefix as query params
          const res = await axios.post(`${API_URL}/range-mapper/import-xml`, form, {
              headers: { 'Content-Type': 'multipart/form-data' },
              params: { scenario_name: 'Imported Network' }
          });
          const topo = res.data?.topology;
          if (!topo?.nodes) throw new Error('No topology returned');

          const newNodes = topo.nodes.map(n => ({
              id: n.id,
              type: 'custom',
              position: n.position || { x: 100, y: 100 },
              data: {
                  label: n.label || 'VM',
                  image: n.config?.image || 'ubuntu-20.04',
                  cpu: n.config?.cpu || 1,
                  ram: n.config?.ram || 1024,
                  assets: n.config?.assets || [],
                  automation: n.config?.automation || null,
                  meta: n.meta || null,
              }
          }));
          setNodes(newNodes);
          const newEdges = (topo.edges || []).map((e, idx) => ({
              id: e.id || `e${idx}`,
              source: e.source,
              target: e.target
          }));
          setEdges(newEdges);
          if (topo.scenario) {
              setScenarioConfig({ ...SCENARIO_DEFAULTS, ...(topo.scenario || {}) });
          }
          setMessageModal({ isOpen: true, title: 'Imported', message: `Imported ${newNodes.length} nodes from XML.`, type: 'success' });
      } catch (err) {
          console.error(err);
          const msg = err?.response?.data?.detail || err.message || 'Import failed';
          setMessageModal({ isOpen: true, title: 'Import Error', message: msg, type: 'error' });
      } finally {
          setImportBusy(false);
      }
  };

  useEffect(() => {
      let timeoutId;
      let isMounted = true;
      
      const fetchRuntime = async () => {
          if (!isMounted) return;
          try {
              const res = await axios.get(`${API_URL}/runtime/vms`);
              if (!isMounted) return;
              setRuntimeVms(res.data || []);
          } catch (err) {
              if (isMounted) console.error('Failed to fetch runtime VMs', err);
          }
      };
      
      const poll = () => {
          fetchRuntime().then(() => {
              if (!isMounted) return;
              const interval = isDeploying ? 2000 : 10000; // Poll faster during deployment
              timeoutId = setTimeout(poll, interval);
          });
      };
      
      fetchRuntime();
      poll();
      
      return () => {
          isMounted = false;
          if (timeoutId) clearTimeout(timeoutId);
      };
  }, [isDeploying]);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge(params, eds)),
    [],
  );

  const handleFileUpload = (event) => {
      const file = event.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (e) => {
          try {
              const content = e.target.result;
              const parsed = yaml.load(content);
              
              if (parsed.nodes) {
                  // Map YAML nodes to ReactFlow nodes
                  const newNodes = parsed.nodes.map(n => ({
                      id: n.id,
                      type: 'custom',
                      position: n.position || { x: 100, y: 100 },
                      data: {
                          label: n.label || 'VM',
                          image: n.config?.image || 'ubuntu-20.04',
                          cpu: n.config?.cpu || 1,
                          ram: n.config?.ram || 1024,
                          assets: n.config?.assets || [],
                          automation: n.config?.automation || null
                      }
                  }));
                  setNodes(newNodes);
              }

              if (parsed.scenario) {
                  setScenarioConfig({ ...SCENARIO_DEFAULTS, ...(parsed.scenario || {}) });
              }
              
              if (parsed.edges) {
                  const newEdges = parsed.edges.map((e, idx) => ({
                      id: e.id || `e${idx}`,
                      source: e.source,
                      target: e.target
                  }));
                  setEdges(newEdges);
              }
              
              setMessageModal({ isOpen: true, title: 'Success', message: 'Topology loaded successfully!', type: 'success' });
          } catch (err) {
              console.error(err);
              setMessageModal({ isOpen: true, title: 'Error', message: "Failed to parse YAML file: " + err.message, type: 'error' });
          }
      };
      reader.readAsText(file);
  };

  const loadPreset = (presetName) => {
      const preset = PREDEFINED_TOPOLOGIES[presetName];
      if (preset) {
          setNodes(preset.nodes);
          setEdges(preset.edges);
          if (preset.scenario) setScenarioConfig({ ...SCENARIO_DEFAULTS, ...(preset.scenario || {}) });
      }
  };

  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow');

      // check if the dropped element is valid
      if (typeof type === 'undefined' || !type) {
        return;
      }

      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      
      const image = event.dataTransfer.getData('image');
      const isRouter = type === 'router';

      const newNode = {
        id: getId(),
        type: 'custom', 
        position,
        data: { 
            label: isRouter ? 'Router' : (image || 'New VM'), 
            image: isRouter ? 'gateway' : (image || 'ubuntu-20.04'), 
            cpu: isRouter ? 1 : 2, 
            ram: isRouter ? 512 : 2048, 
            assets: [] 
        },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [reactFlowInstance],
  );

  const onNodeClick = (event, node) => {
    setSelectedNode(node);
  };

  const updateNodeData = (key, value) => {
    if (!selectedNode) return;
    
    setNodes((nds) =>
      nds.map((node) => {
        if (node.id === selectedNode.id) {
          const newData = { ...node.data, [key]: value };
          // Update selected node as well to reflect changes in UI immediately
          const updatedNode = { ...node, data: newData };
          setSelectedNode(updatedNode);
          return updatedNode;
        }
        return node;
      })
    );
  };

  const addAsset = () => {
      if (!selectedNode) return;
      const currentAssets = selectedNode.data.assets || [];
      updateNodeData('assets', [...currentAssets, { type: 'package', value: '' }]);
  };

  const updateAsset = (index, field, value) => {
      if (!selectedNode) return;
      const currentAssets = [...(selectedNode.data.assets || [])];
      currentAssets[index] = { ...currentAssets[index], [field]: value };
      updateNodeData('assets', currentAssets);
  };
  
  const removeAsset = (index) => {
      if (!selectedNode) return;
      const currentAssets = [...(selectedNode.data.assets || [])];
      currentAssets.splice(index, 1);
      updateNodeData('assets', currentAssets);
  };

  // Restore deploy job on mount
  useEffect(() => {
      const savedJobId = localStorage.getItem('deployJobId');
      if (savedJobId) {
          setDeployJobId(savedJobId);
          setIsDeploying(true);
      }
  }, []);

  // Poll for deploy job status
  useEffect(() => {
      if (!deployJobId) return;

      let isMounted = true;
      let timeoutId;

      const poll = async () => {
          try {
              const jobRes = await axios.get(`${API_URL}/topology/deploy-jobs/${deployJobId}`);
              if (!isMounted) return;
              
              setDeployJob(jobRes.data);
              const status = jobRes.data?.status;
              
              if (status === 'completed' || status === 'failed') {
                  setIsDeploying(false);
                  localStorage.removeItem('deployJobId');
                  setDeployJobId(null);
                  
                  const result = jobRes.data?.result;
                  const results = result?.results || [];
                  const errors = results.filter(r => r.status === 'error');
                  const successes = results.filter(r => r.status === 'success');

                  let message = `Deployment finished!\n`;
                  message += `Successful VMs: ${successes.length}\n`;
                  message += `Failed VMs: ${errors.length}\n`;
                  if (errors.length > 0) {
                      message += "\nErrors:\n";
                      errors.forEach(e => {
                          message += `- ${e.node || e.name || 'Unknown Node'}: ${e.message || e.detail || 'error'}\n`;
                      });
                  }
                  setMessageModal({ isOpen: true, title: 'Deployment Finished', message: message, type: errors.length > 0 ? 'error' : 'success' });
              } else {
                  timeoutId = setTimeout(poll, 1000);
              }
          } catch (e) {
              console.error("Poll error:", e);
              if (isMounted) {
                   if (e.response && e.response.status === 404) {
                       setIsDeploying(false);
                       localStorage.removeItem('deployJobId');
                       setDeployJobId(null);
                   } else {
                       timeoutId = setTimeout(poll, 2000);
                   }
              }
          }
      };

      poll();

      return () => { 
          isMounted = false; 
          if (timeoutId) clearTimeout(timeoutId);
      };
  }, [deployJobId]);

  const handleDeploy = async () => {
      if (nodes.length === 0) {
          setMessageModal({ isOpen: true, title: 'Warning', message: "Cannot deploy an empty topology. Please add some nodes.", type: 'error' });
          return;
      }

      const topology = buildTopologyPayload();
      
      setIsDeploying(true);
      setDeployJobError(null);
      setDeployJob(null);
      setDeployJobId(null);
      try {
          const start = await axios.post(`${API_URL}/topology/deploy-jobs`, topology);
          const jobId = start.data?.job_id;
          if (!jobId) {
              throw new Error('Backend did not return a job_id');
          }
          setDeployJobId(jobId);
          localStorage.setItem('deployJobId', jobId);
      } catch (e) {
          console.error("Deployment error:", e);
          const errorMsg = e.response?.data?.detail || e.message || 'Unknown error';
          setDeployJobError(errorMsg);
          setMessageModal({ isOpen: true, title: 'Deployment Failed', message: 'Deployment failed: ' + errorMsg + "\n\nCheck console for details.", type: 'error' });
          setIsDeploying(false);
      }
  };

  return (
    <div className="dndflow w-full flex flex-col bg-background text-primary" style={{ height: 'calc(100vh - 100px)' }}>
      <div className="flex justify-between items-center p-4 bg-surface border-b border-border">
        <div className="flex items-center gap-4">
            <h2 className="text-xl font-bold text-primary">Network Topology Builder</h2>
            
            <div className="relative group">
                <button className="flex items-center gap-2 bg-surfaceHover hover:bg-surface px-3 py-1.5 rounded text-sm transition-colors text-primary">
                    <FileText size={14} /> Load Preset
                </button>
                <div className="absolute top-full left-0 pt-2 w-48 hidden group-hover:block z-50">
                    <div className="bg-surface border border-border rounded shadow-xl overflow-hidden">
                        <button onClick={() => loadPreset('simple-client-server')} className="block w-full text-left px-4 py-2 hover:bg-surfaceHover text-sm">Simple Client-Server</button>
                    </div>
                </div>
            </div>

            <label className="flex items-center gap-2 bg-surfaceHover hover:bg-surface px-3 py-1.5 rounded text-sm cursor-pointer transition-colors">
                <Upload size={14} /> Upload YAML
                <input type="file" accept=".yaml,.yml" onChange={handleFileUpload} className="hidden" />
            </label>

            <button onClick={() => setShowScenarioSettings(true)} className="flex items-center gap-2 bg-accent/30 hover:bg-accent border border-accent px-3 py-1.5 rounded text-sm transition-colors text-accent">
                <Target size={14} /> Scenario Settings
            </button>

            <button onClick={handleSaveTopology} className="flex items-center gap-2 bg-surfaceHover hover:bg-surface px-3 py-1.5 rounded text-sm transition-colors text-primary">
                <FileText size={14} /> Save Topology
            </button>

            <button onClick={handleClearTopology} className="flex items-center gap-2 bg-red-900/30 hover:bg-red-900/50 border border-red-800 px-3 py-1.5 rounded text-sm transition-colors text-red-200">
                <Trash2 size={14} /> Clear Topology
            </button>
        </div>

        <button 
            onClick={handleDeploy} 
            disabled={isDeploying}
            className={`flex items-center gap-2 px-4 py-2 rounded transition-colors ${isDeploying ? 'bg-green-800 cursor-not-allowed text-secondary' : 'bg-green-600 hover:bg-green-700 text-white'}`}
        >
            {isDeploying ? (
                <>
                    <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></div>
                    Deploying...
                </>
            ) : (
                <>
                    <Play size={16} /> Deploy Network
                </>
            )}
        </button>
      </div>

            {(isDeploying || deployJob) && (
                <div className="bg-background border-b border-border px-4 py-3">
                    <div className="flex items-center justify-between gap-4">
                        <div className="text-sm">
                            <div className="text-primary font-medium">Deploy Progress</div>
                            <div className="text-secondary">
                                {deployJob?.message || (isDeploying ? 'Starting…' : '')}
                                {deployJobId ? ` (job ${deployJobId.slice(0, 8)}…)` : ''}
                            </div>
                            {deployJobError && <div className="text-red-300 mt-1">Error: {deployJobError}</div>}
                        </div>
                        <div className="text-xs text-secondary">
                            Status: {deployJob?.status || (isDeploying ? 'running' : 'idle')}
                        </div>
                    </div>

                    {deployJob?.progress?.downloads && Object.keys(deployJob.progress.downloads).length > 0 && (
                        <div className="mt-3">
                            <div className="text-xs text-secondary mb-2">Downloads</div>
                            <div className="space-y-2">
                                {Object.entries(deployJob.progress.downloads).map(([name, d]) => {
                                    const percent = typeof d?.percent === 'number' ? d.percent : 0;
                                    const status = d?.status || 'pending';
                                    const total = d?.total || 0;
                                    const current = d?.current || 0;
                                    const speed = formatSpeed(d?.speed_bps);
                                    const eta = formatEta(d?.eta_seconds);
                                    const sizeLabel = total > 0 ? `${formatBytes(current)} / ${formatBytes(total)}` : (current > 0 ? `${formatBytes(current)}` : '');
                                    const rightBits = [
                                        total > 0 ? `${percent}%` : null,
                                        sizeLabel || null,
                                        speed || null,
                                        eta ? `ETA ${eta}` : null,
                                        status ? status : null,
                                    ].filter(Boolean);
                                    const label = rightBits.join(' · ');

                                    return (
                                        <div key={name} className="bg-surface border border-border rounded p-2">
                                            <div className="flex items-center justify-between text-xs">
                                                <div className="text-primary truncate" title={name}>{name}</div>
                                                <div className="text-secondary ml-2">{label}</div>
                                            </div>
                                            <div className="mt-2 h-2 w-full bg-surfaceHover rounded overflow-hidden">
                                                <div
                                                    className="h-2 bg-blue-600"
                                                    style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {deployJob?.progress?.nodes && Object.keys(deployJob.progress.nodes).length > 0 && (
                        <div className="mt-3">
                            <div className="text-xs text-secondary mb-2">VMs</div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                {Object.entries(deployJob.progress.nodes).map(([id, n]) => {
                                    const status = n?.status || 'pending';
                                    const msg = n?.message;

                                    const pctMap = {
                                        pending: 0,
                                        creating: 50,
                                        running: 100,
                                        error: 100,
                                    };
                                    const percent = pctMap[status] ?? 0;

                                    const creds = n?.credentials;
                                    return (
                                        <div key={id} className="bg-surface border border-border rounded p-2">
                                            <div className="flex items-center justify-between text-xs">
                                                <div className="text-primary truncate" title={n?.label || id}>{n?.label || id}</div>
                                                <div className={`ml-2 ${status === 'error' ? 'text-red-300' : 'text-secondary'}`}>{status}</div>
                                            </div>
                                            {msg && <div className="text-xs text-red-300 mt-1 truncate" title={msg}>{msg}</div>}
                                            {creds?.username && creds?.password && (
                                                <div className="text-xs bg-blue-900/40 text-blue-300 px-2 py-1 rounded mt-1 flex items-center gap-3">
                                                    <span>Login: <code className="bg-background px-1 py-0.5 rounded font-mono">{creds.username}</code></span>
                                                    <span>Pass: <code className="bg-background px-1 py-0.5 rounded font-mono">{creds.password}</code></span>
                                                </div>
                                            )}
                                            <div className="mt-2 h-2 w-full bg-surfaceHover rounded overflow-hidden">
                                                <div
                                                    className={status === 'error' ? 'h-2 bg-red-600' : 'h-2 bg-green-600'}
                                                    style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            )}
      
      <div className="flex-grow flex h-full overflow-hidden">
        <ReactFlowProvider>
            <div className="w-64 bg-background border-r border-border p-4 flex flex-col gap-4 z-10 overflow-y-auto">
                <div className="text-secondary text-sm font-medium mb-2">Network Nodes</div>

                <div className="bg-surface border border-border rounded p-3">
                    <div className="text-xs text-secondary font-medium mb-2">Scan & Import (Nmap)</div>
                    <input
                        className="w-full bg-background border border-border rounded px-2 py-1 text-sm text-primary"
                        value={scanTarget}
                        onChange={(e) => setScanTarget(e.target.value)}
                        placeholder="192.168.1.0/24"
                    />
                    <label className="mt-2 flex items-center gap-2 text-[11px] text-secondary select-none">
                        <input
                            type="checkbox"
                            checked={scanDryRun}
                            onChange={(e) => setScanDryRun(e.target.checked)}
                        />
                        Dry run (don’t scan)
                    </label>
                    <button
                        onClick={scanAndImport}
                        disabled={scanBusy}
                        className="mt-2 w-full bg-accent hover:bg-accentHover disabled:opacity-50 text-white text-sm px-3 py-2 rounded"
                        title="Requires backend env var RANGE_MAPPER_ENABLE=1"
                    >
                        {scanBusy ? 'Scanning...' : 'Scan & Import'}
                    </button>

                    <div className="mt-3 border-t border-border pt-3">
                        <div className="text-xs text-secondary font-medium mb-2">Import from Nmap XML</div>
                        <input
                            type="file"
                            accept=".xml"
                            className="w-full text-[11px] text-secondary"
                            onChange={(e) => {
                                const f = e.target.files?.[0];
                                if (f) importXmlAndConvert(f);
                                e.target.value = null;
                            }}
                            disabled={importBusy}
                        />
                        <div className="mt-2 text-[11px] text-muted">Uploads XML to the server and imports it.</div>
                    </div>
                    <div className="mt-2 text-[11px] text-muted">
                        Runs on the server. Only scans private ranges by default.
                    </div>
                </div>
                
                <div className="dndnode output p-3 bg-purple-900/30 border border-purple-700 rounded cursor-grab text-purple-100 hover:bg-purple-900/50 transition-colors flex items-center gap-2" onDragStart={(event) => event.dataTransfer.setData('application/reactflow', 'router')} draggable>
                    <Flag size={16} /> Router / Gateway
                </div>

                <div className="text-secondary text-sm font-medium mt-4 mb-2">Available Images</div>
                {availableImages.length === 0 && (
                    <div className="text-xs text-muted italic">No images found.</div>
                )}
                {availableImages.map((img) => (
                    <div 
                        key={img.path}
                        className="dndnode input p-3 bg-blue-900/30 border border-blue-700 rounded cursor-grab text-blue-100 hover:bg-blue-900/50 transition-colors flex items-center gap-2 mb-2" 
                        onDragStart={(event) => {
                            event.dataTransfer.setData('application/reactflow', 'vm');
                            event.dataTransfer.setData('image', img.name);
                        }} 
                        draggable
                    >
                        <Shield size={16} /> {img.name}
                    </div>
                ))}
                
                <div className="text-secondary text-sm font-medium mt-4 mb-2">Generic Nodes</div>
                <div className="dndnode input p-3 bg-surface border border-border rounded cursor-grab text-primary hover:bg-surfaceHover transition-colors flex items-center gap-2" onDragStart={(event) => event.dataTransfer.setData('application/reactflow', 'vm')} draggable>
                    <Shield size={16} /> Generic VM
                </div>
            </div>

            <div className="flex-grow h-full relative" ref={reactFlowWrapper}>
                <div className="absolute top-0 left-0 right-0 z-20 bg-background/95 border-b border-surface px-4 py-3 space-y-3">
                    <div>
                        <div className="text-sm text-primary font-semibold">Live VM IPs</div>
                        {nodes.length === 0 && <div className="text-xs text-secondary">No nodes yet.</div>}
                        {vmIpList.length > 0 && (
                            <div className="grid md:grid-cols-2 gap-2 mt-2">
                                {vmIpList.map(item => (
                                    <div key={item.id} className="bg-surface border border-border rounded p-2 text-xs text-primary flex justify-between">
                                        <div className="truncate" title={item.label}>{item.label}</div>
                                        <div className="text-secondary ml-2" title={item.info ? (item.ip || 'No IP yet') : 'VM not found'}>
                                            {item.info ? (item.ip || 'IP pending') : 'not deployed'}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {connectionList.length > 0 && (
                        <div>
                            <div className="text-sm text-primary font-semibold">Connections</div>
                            <div className="grid md:grid-cols-2 gap-2 mt-2 text-xs text-primary">
                                {connectionList.map(conn => (
                                    <div key={conn.id} className="bg-surface border border-border rounded px-2 py-1 flex justify-between items-center">
                                        <div className="truncate" title={conn.srcLabel}>{conn.srcLabel} {conn.srcIp ? `(${conn.srcIp})` : ''}</div>
                                        <div className="text-secondary mx-2">↔</div>
                                        <div className="truncate text-right" title={conn.dstLabel}>{conn.dstLabel} {conn.dstIp ? `(${conn.dstIp})` : ''}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onConnect={onConnect}
                    onInit={setReactFlowInstance}
                    onDrop={onDrop}
                    onDragOver={onDragOver}
                    onNodeClick={onNodeClick}
                    onMove={() => {
                        // Save viewport position as user moves around
                        if (reactFlowInstance && viewportRestored) {
                            const saved = localStorage.getItem('networkTopology');
                            if (saved) {
                                try {
                                    const topology = JSON.parse(saved);
                                    topology.viewport = reactFlowInstance.getViewport();
                                    localStorage.setItem('networkTopology', JSON.stringify(topology));
                                } catch (err) {
                                    // Silently fail to avoid console spam
                                }
                            }
                        }
                    }}
                    nodeTypes={nodeTypes}
                    fitView={false}
                    className="bg-background"
                >
                    <Controls />
                    <Background color="#333" gap={16} />
                </ReactFlow>
            </div>

            {showScenarioSettings && (
                <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
                    <div className="bg-surface p-6 rounded-xl border border-border w-full max-w-md">
                        <h3 className="text-xl font-bold mb-4 text-primary">Scenario Configuration</h3>
                        
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm text-secondary mb-1">Scenario Name</label>
                                <input 
                                    type="text" 
                                    value={scenarioConfig.name}
                                    onChange={(e) => setScenarioConfig({...scenarioConfig, name: e.target.value})}
                                    className="w-full bg-background border border-border rounded p-2 text-primary"
                                />
                            </div>

                            <div>
                                <label className="block text-sm text-secondary mb-1">Network Prefix (optional)</label>
                                <input
                                    type="text"
                                    value={scenarioConfig.network_prefix || ''}
                                    onChange={(e) => setScenarioConfig({ ...scenarioConfig, network_prefix: e.target.value })}
                                    placeholder="Leave blank for a random per-deploy network name"
                                    className="w-full bg-background border border-border rounded p-2 text-primary"
                                />
                                <div className="text-xs text-secondary mt-1">
                                    If set, libvirt networks will be named like <span className="font-mono">cyberange-&lt;prefix&gt;-c0</span>.
                                </div>
                            </div>
                            
                            <div>
                                <label className="block text-sm text-secondary mb-1">Team / Type</label>
                                <select 
                                    value={scenarioConfig.team}
                                    onChange={(e) => setScenarioConfig({...scenarioConfig, team: e.target.value})}
                                    className="w-full bg-background border border-border rounded p-2 text-primary"
                                >
                                    <option value="blue">Blue Team (Defense)</option>
                                    <option value="red">Red Team (Offense)</option>
                                    <option value="green">Green Team (Forensics/Infra)</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-sm text-secondary mb-1">Difficulty</label>
                                <select 
                                    value={scenarioConfig.difficulty}
                                    onChange={(e) => setScenarioConfig({...scenarioConfig, difficulty: e.target.value})}
                                    className="w-full bg-background border border-border rounded p-2 text-primary"
                                >
                                    <option value="easy">Easy</option>
                                    <option value="medium">Medium</option>
                                    <option value="hard">Hard</option>
                                    <option value="expert">Expert</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-sm text-secondary mb-1">Objective / Description</label>
                                <textarea 
                                    value={scenarioConfig.objective}
                                    onChange={(e) => setScenarioConfig({...scenarioConfig, objective: e.target.value})}
                                    className="w-full bg-background border border-border rounded p-2 h-32 text-primary"
                                />
                            </div>
                        </div>

                        <div className="flex justify-end mt-6">
                            <button onClick={() => setShowScenarioSettings(false)} className="bg-accent hover:bg-accentHover text-primary px-4 py-2 rounded">
                                Save Configuration
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {selectedNode && (
                <div className="w-80 bg-background border-l border-border p-4 overflow-y-auto z-10 shadow-xl">
                    <div className="flex justify-between items-center mb-4">
                        <h3 className="text-lg font-semibold text-primary">Configuration</h3>
                        <button onClick={() => setSelectedNode(null)} className="text-secondary hover:text-primary text-xl">&times;</button>
                    </div>
                    
                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm text-secondary mb-1">Node Name</label>
                            <input 
                                type="text" 
                                value={selectedNode.data.label} 
                                onChange={(e) => updateNodeData('label', e.target.value)}
                                className="w-full bg-surface border border-border rounded p-2 text-primary focus:border-accent outline-none"
                            />
                        </div>
                        
                        <div>
                            <label className="block text-sm text-secondary mb-1">OS Image</label>
                            <select 
                                value={selectedNode.data.image} 
                                onChange={(e) => updateNodeData('image', e.target.value)}
                                className="w-full bg-surface border border-border rounded p-2 text-primary focus:border-accent outline-none"
                            >
                                <option value="ubuntu-20.04">Ubuntu 20.04 LTS</option>
                                <option value="kali-linux">Kali Linux</option>
                                <option value="windows-10">Windows 10</option>
                                <option value="gateway">Gateway/Router</option>
                                {availableImages.map(img => (
                                    <option key={img.path} value={img.name}>{img.name} (Custom)</option>
                                ))}
                            </select>
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="block text-sm text-secondary mb-1">CPU Cores</label>
                                <input 
                                    type="number" 
                                    value={selectedNode.data.cpu} 
                                    onChange={(e) => updateNodeData('cpu', parseInt(e.target.value))}
                                    className="w-full bg-surface border border-border rounded p-2 text-primary focus:border-accent outline-none"
                                />
                            </div>
                            <div>
                                <label className="block text-sm text-secondary mb-1">RAM (MB)</label>
                                <input 
                                    type="number" 
                                    value={selectedNode.data.ram} 
                                    onChange={(e) => updateNodeData('ram', parseInt(e.target.value))}
                                    className="w-full bg-surface border border-border rounded p-2 text-primary focus:border-accent outline-none"
                                />
                            </div>
                        </div>

                        <div className="border-t border-border pt-4">
                            <label className="block text-sm text-secondary mb-2">VM Credentials</label>
                            <div className="grid grid-cols-2 gap-2 mb-4">
                                <div>
                                    <label className="block text-xs text-secondary mb-1">Username</label>
                                    <input
                                        type="text"
                                        value={selectedNode.data.username || ''}
                                        onChange={(e) => updateNodeData('username', e.target.value)}
                                        placeholder="trainee"
                                        className="w-full bg-surface border border-border rounded p-2 text-sm text-primary focus:border-accent outline-none"
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs text-secondary mb-1">Password</label>
                                    <input
                                        type="text"
                                        value={selectedNode.data.password || ''}
                                        onChange={(e) => updateNodeData('password', e.target.value)}
                                        placeholder="auto-generated"
                                        className="w-full bg-surface border border-border rounded p-2 text-sm text-primary focus:border-accent outline-none"
                                    />
                                </div>
                            </div>
                            <p className="text-xs text-secondary italic mb-4">Leave blank to auto-generate</p>
                        </div>

                        <div className="border-t border-border pt-4">
                            <div className="flex justify-between items-center mb-2">
                                <label className="block text-sm text-secondary">Assets & Scripts</label>
                                <button onClick={addAsset} className="text-xs bg-accent px-2 py-1 rounded text-primary hover:bg-accentHover flex items-center gap-1">
                                    <Plus size={12} /> Add
                                </button>
                            </div>
                            
                            <div className="space-y-2">
                                {selectedNode.data.assets && selectedNode.data.assets.map((asset, idx) => (
                                    <div key={idx} className="bg-surface p-2 rounded border border-border">
                                        <div className="flex gap-2 mb-2">
                                            <select 
                                                value={asset.type}
                                                onChange={(e) => updateAsset(idx, 'type', e.target.value)}
                                                className="bg-surfaceHover text-xs rounded p-1 text-primary border border-border"
                                            >
                                                <option value="package">Install Package</option>
                                                <option value="command">Run Command</option>
                                            </select>
                                            <button onClick={() => removeAsset(idx)} className="ml-auto text-red-400 hover:text-red-300">
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                        <input 
                                            type="text" 
                                            value={asset.value}
                                            onChange={(e) => updateAsset(idx, 'value', e.target.value)}
                                            placeholder={asset.type === 'package' ? 'e.g. nginx' : 'e.g. systemctl start nginx'}
                                            className="w-full bg-surfaceHover border border-border rounded p-1 text-sm text-primary focus:border-accent outline-none"
                                        />
                                    </div>
                                ))}
                                {(!selectedNode.data.assets || selectedNode.data.assets.length === 0) && (
                                    <div className="text-xs text-secondary italic text-center py-2">No assets defined</div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </ReactFlowProvider>
      </div>

      <Modal
        isOpen={messageModal.isOpen}
        onClose={() => setMessageModal({ ...messageModal, isOpen: false })}
        title={messageModal.title}
        footer={
            <button onClick={() => setMessageModal({ ...messageModal, isOpen: false })} className="px-4 py-2 bg-surface hover:bg-surfaceHover text-primary rounded">Close</button>
        }
      >
        <div className={`text-sm whitespace-pre-wrap ${messageModal.type === 'error' ? 'text-red-400' : messageModal.type === 'success' ? 'text-green-400' : 'text-secondary'}`}>
            {messageModal.message}
        </div>
      </Modal>
    </div>
  );
};

export default NetworkBuilder;
