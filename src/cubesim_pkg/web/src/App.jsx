import React, { useState, useRef, useEffect } from 'react';
import { RotateCw, RotateCcw, RefreshCw, Eye, Search, Play } from 'lucide-react';
import * as THREE from 'three';

class CubeState {
  constructor(pieces) {
    this.pieces = pieces || this.initializePieces();
  }
  
  initializePieces() {
    const pieces = {};
    for (let x = -1; x <= 1; x++) {
      for (let y = -1; y <= 1; y++) {
        for (let z = -1; z <= 1; z++) {
          const key = `${x},${y},${z}`;
          pieces[key] = { x, y, z, originalKey: key };
        }
      }
    }
    return pieces;
  }
  
  toHash() {
    const positions = Object.values(this.pieces)
      .sort((a, b) => a.originalKey.localeCompare(b.originalKey))
      .map(p => `${p.originalKey}:(${p.x},${p.y},${p.z})`)
      .join('|');
    return positions;
  }
  
  clone() {
    const newPieces = {};
    Object.entries(this.pieces).forEach(([key, piece]) => {
      newPieces[key] = { ...piece };
    });
    return new CubeState(newPieces);
  }
  
  rotate(face, clockwise = true) {
    const newState = this.clone();
    const pieces = Object.values(newState.pieces);
    
    pieces.forEach(piece => {
      let { x, y, z } = piece;
      let newX = x, newY = y, newZ = z;
      let shouldRotate = false;
      
      if (face === 'F') {
        shouldRotate = z === 1;
        if (shouldRotate) {
          if (clockwise) {
            [newX, newY] = [-y, x];
          } else {
            [newX, newY] = [y, -x];
          }
        }
      } else if (face === 'B') {
        shouldRotate = z === -1;
        if (shouldRotate) {
          if (clockwise) {
            [newX, newY] = [y, -x];
          } else {
            [newX, newY] = [-y, x];
          }
        }
      } else if (face === 'U') {
        shouldRotate = y === 1;
        if (shouldRotate) {
          if (clockwise) {
            [newX, newZ] = [z, -x];
          } else {
            [newX, newZ] = [-z, x];
          }
        }
      } else if (face === 'D') {
        shouldRotate = y === -1;
        if (shouldRotate) {
          if (clockwise) {
            [newX, newZ] = [-z, x];
          } else {
            [newX, newZ] = [z, -x];
          }
        }
      } else if (face === 'R') {
        shouldRotate = x === 1;
        if (shouldRotate) {
          if (clockwise) {
            [newY, newZ] = [-z, y];
          } else {
            [newY, newZ] = [z, -y];
          }
        }
      } else if (face === 'L') {
        shouldRotate = x === -1;
        if (shouldRotate) {
          if (clockwise) {
            [newY, newZ] = [z, -y];
          } else {
            [newY, newZ] = [-z, y];
          }
        }
      }
      
      piece.x = newX;
      piece.y = newY;
      piece.z = newZ;
    });
    
    const reconstructed = {};
    pieces.forEach(piece => {
      const key = `${piece.x},${piece.y},${piece.z}`;
      reconstructed[key] = piece;
    });
    newState.pieces = reconstructed;
    
    return newState;
  }
  
  findPiecePosition(originalKey) {
    const piece = Object.values(this.pieces).find(p => p.originalKey === originalKey);
    return piece ? `${piece.x},${piece.y},${piece.z}` : null;
  }
}

// startState: 현재 큐브의 상태 객체
// targetPieceKey: 움직이고 싶은 조각의 원래 키 (예: '0,1,1')
// targetZoneCoords: 도착해야 하는 목표 좌표들의 배열 (B타입 위치들)
function findShortestPath(startState, targetPieceKey, targetZoneCoords) {
  // 사용 가능한 움직임 (PDF 1번 목표 달성을 위해 필요한 회전들)
  // 탐색 속도를 위해 필요한 축만 넣거나 전체를 넣을 수 있습니다.
  const moves = ['U', "U'", 'R', "R'", 'F', "F'", 'B', "B'", 'L', "L'", 'D', "D'"];
  
  // 중요: 매번 새 큐브가 아니라, '현재 상태'를 복제해서 시작해야 함
  const initialCube = startState.clone();
  
  // 목표 상태인지 확인하는 함수
  function isGoalState(state) {
    // 현재 큐브 상태에서, 우리가 추적하는 조각이 어디에 있는지 확인
    const currentPos = state.findPiecePosition(targetPieceKey);
    // 그 위치가 목표 구역(B타입 바퀴 위치) 중 하나에 포함되는가?
    return targetZoneCoords.includes(currentPos);
  }
  
  // BFS 탐색 시작
  const queue = [{ state: initialCube, path: [] }];
  // 방문 기록 (무한 루프 방지)
  const visited = new Set([initialCube.toHash()]);
  
  let nodesExplored = 0;
  const maxNodes = 100000; // 탐색 깊이 제한 (성능 조절)
  
  while (queue.length > 0) {
    const current = queue.shift();
    const state = current.state;
    const path = current.path;
    
    nodesExplored++;
    if (nodesExplored > maxNodes) break;
    
    // 목표 달성 확인
    if (isGoalState(state)) {
      return {
        success: true,
        path: path,
        length: path.length,
        nodesExplored: nodesExplored
      };
    }
    
    // 다음 수 탐색
    for (const move of moves) {
      // 마지막 움직임의 정반대 움직임은 불필요하므로 최적화 (예: R 다음에 R'는 안 함)
      if (path.length > 0) {
        const lastMove = path[path.length - 1];
        const isInverse = (m1, m2) => m1[0] === m2[0] && m1.length !== m2.length;
        if (isInverse(lastMove, move)) continue;
      }

      const face = move.replace("'", "");
      const clockwise = !move.includes("'");
      
      // 상태 회전
      const newState = state.rotate(face, clockwise);
      const hash = newState.toHash();
      
      if (!visited.has(hash)) {
        visited.add(hash);
        queue.push({
          state: newState,
          path: [...path, move]
        });
      }
    }
  }
  
  return {
    success: false,
    message: nodesExplored >= maxNodes ? '탐색 범위 초과 (너무 멉니다)' : '해를 찾을 수 없음',
    nodesExplored: nodesExplored
  };
}

function rotateColors(colors, axis, clockwise) {
  const c = { ...colors };

  if (axis === 'x') {
    if (clockwise) {
      c.py = colors.nz;
      c.pz = colors.py;
      c.ny = colors.pz;
      c.nz = colors.ny;
    } else {
      c.py = colors.pz;
      c.pz = colors.ny;
      c.ny = colors.nz;
      c.nz = colors.py;
    }
  }

  if (axis === 'y') {
    if (clockwise) {
      c.px = colors.pz;
      c.pz = colors.nx;
      c.nx = colors.nz;
      c.nz = colors.px;
    } else {
      c.px = colors.nz;
      c.pz = colors.px;
      c.nx = colors.pz;
      c.nz = colors.nx;
    }
  }

  if (axis === 'z') {
    if (clockwise) {
      c.px = colors.py;
      c.py = colors.nx;
      c.nx = colors.ny;
      c.ny = colors.px;
    } else {
      c.px = colors.ny;
      c.py = colors.px;
      c.nx = colors.py;
      c.ny = colors.nx;
    }
  }

  return c;
}

const CubeSimulator = () => {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const rendererRef = useRef(null);
  const cameraRef = useRef(null);
  const cubesRef = useRef({});
  const animationRef = useRef({ theta: Math.PI / 4, phi: Math.PI / 4 });
  const isDraggingRef = useRef(false);
  
  const [cubeState, setCubeState] = useState(() => initializeCube());
  const [history, setHistory] = useState([]);
  const [isRotating, setIsRotating] = useState(false);
  const [visualMode, setVisualMode] = useState('wheel');
  const [commandInput, setCommandInput] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [previousMousePosition, setPreviousMousePosition] = useState({ x: 0, y: 0 });
  const [trackedPiece, setTrackedPiece] = useState('0,1,-1');
  const handleTrackedPieceChange = (e) => {
    const val = e.target.value.replace(/\s/g, ''); 
    setTrackedPiece(val);
  };
  const [searchResult, setSearchResult] = useState(null);
  const [isSearching, setIsSearching] = useState(false);
  
  function initializeCube() {
    const state = {};
    for (let x = -1; x <= 1; x++) {
      for (let y = -1; y <= 1; y++) {
        for (let z = -1; z <= 1; z++) {
          const key = `${x},${y},${z}`;
          state[key] = { 
            x, y, z, 
            type: getPieceType(x, y, z),
            wheelType: getWheelType(x, y, z),
            originalKey: key,
            colors: {
              px: x === 1 ? 0x0000ff : null,
              nx: x === -1 ? 0x00ff00 : null,
              py: y === 1 ? 0xffffff : null,
              ny: y === -1 ? 0xffff00 : null,
              pz: z === 1 ? 0xff0000 : null,
              nz: z === -1 ? 0xff8800 : null
            }
          };
        }
      }
    }
    return state;
  }
  
  function getPieceType(x, y, z) {
    const faceCount = [x, y, z].filter(v => v === -1 || v === 1).length;
    if (faceCount === 0) return 'center';
    if (faceCount === 1) return 'center-face';
    if (faceCount === 2) return 'edge';
    return 'corner';
  }
  
  function getWheelType(x, y, z) {
    if (getPieceType(x, y, z) !== 'edge') return null;
    
    if ((x === 0 && y === 1 && z === 1) ||
        (x === 0 && y === 1 && z === -1) ||
        (x === 1 && y === 1 && z === 0) ||
        (x === -1 && y === 1 && z === 0)) {
      return 'A';
    }
    
    if ((x === 1 && y === 0 && z === 1) ||
        (x === 1 && y === 0 && z === -1) ||
        (x === -1 && y === 0 && z === 1) ||
        (x === -1 && y === 0 && z === -1)) {
      return 'B';
    }
    
    return null;
  }
  
  function getCubeMaterials(piece, mode) {
    const isTracked = piece.originalKey === trackedPiece;
    
    if (mode === 'wheel') {
      let color = 0x888888;
      if (piece.wheelType === 'A') color = 0x4ade80;
      if (piece.wheelType === 'B') color = 0x3b82f6;
      if (isTracked) color = 0xfbbf24;
      
      const opacity = (!piece.wheelType && !isTracked) ? 0.3 : 1;
      return new THREE.MeshPhongMaterial({ 
        color,
        transparent: opacity < 1,
        opacity
      });
    }
    
    if (mode === 'color' || mode === 'both') {
      const faceColors = [
        piece.colors.px || 0x202020,
        piece.colors.nx || 0x202020,
        piece.colors.py || 0x202020,
        piece.colors.ny || 0x202020,
        piece.colors.pz || 0x202020,
        piece.colors.nz || 0x202020
      ];
      
      const isImportant = piece.wheelType || isTracked;
      const opacity = (mode === 'both' && !isImportant) ? 0.3 : 1;
      
      const materials = faceColors.map(color => {
        return new THREE.MeshPhongMaterial({ 
          color,
          transparent: opacity < 1,
          opacity
        });
      });
      
      return materials;
    }
  }
  
  useEffect(() => {
    if (!mountRef.current) return;
    
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f0f0);
    sceneRef.current = scene;
    
    const camera = new THREE.PerspectiveCamera(75, mountRef.current.clientWidth / mountRef.current.clientHeight, 0.1, 1000);
    camera.position.set(5, 5, 5);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;
    
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(mountRef.current.clientWidth, mountRef.current.clientHeight);
    mountRef.current.appendChild(renderer.domElement);
    rendererRef.current = renderer;
    
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.5);
    directionalLight.position.set(10, 10, 10);
    scene.add(directionalLight);
    
    const gridHelper = new THREE.GridHelper(10, 10, 0xcccccc, 0xeeeeee);
    scene.add(gridHelper);
    
    const axesHelper = new THREE.AxesHelper(3);
    scene.add(axesHelper);
    
    const createTextSprite = (text, color) => {
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      canvas.width = 256;
      canvas.height = 256;
      context.font = 'Bold 120px Arial';
      context.fillStyle = color;
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      context.fillText(text, 128, 128);
      
      const texture = new THREE.CanvasTexture(canvas);
      const spriteMaterial = new THREE.SpriteMaterial({ map: texture });
      const sprite = new THREE.Sprite(spriteMaterial);
      sprite.scale.set(0.8, 0.8, 1);
      return sprite;
    };
    
    const xLabel = createTextSprite('X', '#ff0000');
    xLabel.position.set(3.5, 0, 0);
    scene.add(xLabel);
    
    const yLabel = createTextSprite('Y', '#00ff00');
    yLabel.position.set(0, 3.5, 0);
    scene.add(yLabel);
    
    const zLabel = createTextSprite('Z', '#0000ff');
    zLabel.position.set(0, 0, 3.5);
    scene.add(zLabel);
    
    let autoRotateAngle = animationRef.current.theta;
    function animate() {
      requestAnimationFrame(animate);
      
      if (!isDraggingRef.current) {
        autoRotateAngle += 0.003;
        animationRef.current.theta = autoRotateAngle;
      } else {
        autoRotateAngle = animationRef.current.theta;
      }
      
      const radius = 7;
      camera.position.x = radius * Math.sin(animationRef.current.phi) * Math.cos(animationRef.current.theta);
      camera.position.y = radius * Math.cos(animationRef.current.phi);
      camera.position.z = radius * Math.sin(animationRef.current.phi) * Math.sin(animationRef.current.theta);
      camera.lookAt(0, 0, 0);
      
      renderer.render(scene, camera);
    }
    animate();
    
    return () => {
      if (mountRef.current && renderer.domElement) {
        mountRef.current.removeChild(renderer.domElement);
      }
      renderer.dispose();
    };
  }, []);
  
  useEffect(() => {
    if (!sceneRef.current) return;
    
    Object.values(cubesRef.current).forEach(cube => {
      sceneRef.current.remove(cube);
    });
    cubesRef.current = {};
    
    Object.entries(cubeState).forEach(([key, piece]) => {
      const geometry = new THREE.BoxGeometry(0.9, 0.9, 0.9);
      const materials = getCubeMaterials(piece, visualMode);
      const cube = new THREE.Mesh(geometry, materials);
      
      cube.position.x = piece.x;
      cube.position.y = piece.y;
      cube.position.z = piece.z;
      
      const edges = new THREE.EdgesGeometry(geometry);
      const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x000000, linewidth: 2 }));
      cube.add(line);
      
      sceneRef.current.add(cube);
      cubesRef.current[key] = cube;
    });
  }, [cubeState, visualMode, trackedPiece]);
  
  function rotateFace(face, layer, clockwise) {
    if (isRotating) return;
    setIsRotating(true);
    
    const newState = JSON.parse(JSON.stringify(cubeState));
    const pieces = Object.values(newState);
    
    pieces.forEach(piece => {
      let x = piece.x;
      let y = piece.y;
      let z = piece.z;
      let colors = piece.colors;
      let newX = x;
      let newY = y;
      let newZ = z;
      let newColors = { ...colors };
      let shouldRotate = false;
      
      if (face === 'F') {
        shouldRotate = z === 1;
        if (shouldRotate) {
          if (clockwise) {
            newX = -y;
            newY = x;
          } else {
            newX = y;
            newY = -x;
          }
          newColors = rotateColors(colors, 'z', clockwise);
        }
      } else if (face === 'B') {
        shouldRotate = z === -1;
        if (shouldRotate) {
          if (clockwise) {
            newX = y;
            newY = -x;
          } else {
            newX = -y;
            newY = x;
          }
          newColors = rotateColors(colors, 'z', clockwise);
        }
      } else if (face === 'U') {
        shouldRotate = y === 1;
        if (shouldRotate) {
          if (clockwise) {
            newX = z;
            newZ = -x;
          } else {
            newX = -z;
            newZ = x;
          }
          newColors = rotateColors(colors, 'y', clockwise);
        }
      } else if (face === 'D') {
        shouldRotate = y === -1;
        if (shouldRotate) {
          if (clockwise) {
            newX = -z;
            newZ = x;
          } else {
            newX = z;
            newZ = -x;
          }
          newColors = rotateColors(colors, 'y', !clockwise);
        }
      } else if (face === 'R') {
        shouldRotate = x === 1;
        if (shouldRotate) {
          if (clockwise) {
            newY = -z;
            newZ = y;
          } else {
            newY = z;
            newZ = -y;
          }
          newColors = rotateColors(colors, 'x', clockwise);
        }
      } else if (face === 'L') {
        shouldRotate = x === -1;
        if (shouldRotate) {
          if (clockwise) {
            newY = z;
            newZ = -y;
          } else {
            newY = -z;
            newZ = y;
          }
          newColors = rotateColors(colors, 'x', !clockwise);
        }
      }
      
      piece.x = newX;
      piece.y = newY;
      piece.z = newZ;
      piece.colors = newColors;
    });
    
    const reconstructed = {};
    pieces.forEach(piece => {
      const key = `${piece.x},${piece.y},${piece.z}`;
      reconstructed[key] = piece;
    });
    
    const notation = layer ? `${layer}${clockwise ? '' : "'"}` : `${face}${clockwise ? '' : "'"}`;
    setCubeState(reconstructed);
    setHistory(prev => [...prev, notation]);
    
    setTimeout(() => setIsRotating(false), 300);
  }
  
  function executeCommands(commandStr) {
    const commands = commandStr.trim().toUpperCase().split(/\s+/);
    const validCommands = ['F', "F'", 'B', "B'", 'U', "U'", 'D', "D'", 'R', "R'", 'L', "L'", 
                          'S', "S'", 'E', "E'", 'M', "M'"];
    
    let delay = 0;
    commands.forEach((cmd) => {
      if (!validCommands.includes(cmd)) {
        alert(`잘못된 명령어: ${cmd}`);
        return;
      }
      
      setTimeout(() => {
        const isPrime = cmd.endsWith("'");
        const baseFace = cmd.replace("'", "");
        
        if (['S', 'E', 'M'].includes(baseFace)) {
          const faceMap = { 'S': 'F', 'E': 'U', 'M': 'R' };
          rotateFace(faceMap[baseFace], baseFace, !isPrime);
        } else {
          rotateFace(baseFace, null, !isPrime);
        }
      }, delay);
      
      delay += 350;
    });
  }
  
  function runAlgorithmSearch() {
    setIsSearching(true);
    setSearchResult(null);
    
    // UI 렌더링을 막지 않기 위해 setTimeout 사용
    setTimeout(() => {
      // 1. 현재 큐브 상태를 객체화
      const currentCubeStateObj = new CubeState(cubeState);

      // 2. 목표 정의 (PDF 1번: A타입 -> B타입 위치로 이동)
      // A타입 위치(출발지 후보가 될 수 있음): ['0,1,1', '0,1,-1', '1,1,0', '-1,1,0']
      // B타입 위치(목표지): ['1,0,1', '1,0,-1', '-1,0,1', '-1,0,-1']
      const bWheelPositions = ['1,0,1', '1,0,-1', '-1,0,1', '-1,0,-1'];
      
      // 3. 현재 추적 중인 조각이 유효한지 확인
      const targetPiece = trackedPiece.replace(/\s/g, ''); // 공백 제거
      
      // 4. 탐색 시작 (현재 상태, 목표 조각, 목표 위치들)
      const result = findShortestPath(currentCubeStateObj, targetPiece, bWheelPositions);
      
      setSearchResult(result);
      setIsSearching(false);
    }, 100);
  }
  
  const handleMouseDown = (e) => {
    setIsDragging(true);
    isDraggingRef.current = true;
    setPreviousMousePosition({ x: e.clientX, y: e.clientY });
  };
  
  const handleMouseMove = (e) => {
    if (!isDraggingRef.current) return;
    
    const deltaX = e.clientX - previousMousePosition.x;
    const deltaY = e.clientY - previousMousePosition.y;
    
    animationRef.current.theta = animationRef.current.theta + deltaX * 0.01;
    animationRef.current.phi = Math.max(0.1, Math.min(Math.PI - 0.1, animationRef.current.phi + deltaY * 0.01));
    
    setPreviousMousePosition({ x: e.clientX, y: e.clientY });
  };
  
  const handleMouseUp = () => {
    setIsDragging(false);
    isDraggingRef.current = false;
  };
  
  function reset() {
    setCubeState(initializeCube());
    setHistory([]);
    setSearchResult(null);
  }
  
  const wheelPieces = Object.values(cubeState).filter(p => p.wheelType === 'A' || p.wheelType === 'B');
  const aWheels = wheelPieces.filter(p => p.wheelType === 'A');
  const bWheels = wheelPieces.filter(p => p.wheelType === 'B');
  const trackedPieceObj = Object.values(cubeState).find(p => p.originalKey === trackedPiece);
  
  const notations = {
    U: "Up (위, 흰색, y=1)",
    R: "Right (오른쪽, 파랑, x=1)",
    L: "Left (왼쪽, 초록, x=-1)",
    B: "Back (뒤, 주황, z=-1)",
  };
  
  return React.createElement('div', { className: 'p-6 max-w-6xl mx-auto' },
    React.createElement('h1', { className: 'text-2xl font-bold mb-4' }, '3×3 Rubik\'s Cube Sim'),
    
    React.createElement('div', { className: 'grid grid-cols-1 lg:grid-cols-3 gap-6' },
      React.createElement('div', { className: 'lg:col-span-2' },
        React.createElement('div', {
          ref: mountRef,
          className: 'w-full bg-white rounded-lg shadow-lg cursor-grab active:cursor-grabbing',
          style: { height: '500px' },
          onMouseDown: handleMouseDown,
          onMouseMove: handleMouseMove,
          onMouseUp: handleMouseUp,
          onMouseLeave: handleMouseUp
        }),
        
        React.createElement('div', { className: 'mt-3 flex gap-2' },
          React.createElement('button', {
            onClick: () => setVisualMode('wheel'),
            className: `flex-1 px-3 py-2 rounded text-sm font-medium ${visualMode === 'wheel' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-700'}`
          },
            React.createElement(Eye, { className: 'inline w-4 h-4 mr-1' }),
            '바퀴 모드'
          ),
          React.createElement('button', {
            onClick: () => setVisualMode('color'),
            className: `flex-1 px-3 py-2 rounded text-sm font-medium ${visualMode === 'color' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-700'}`
          },
            React.createElement(Eye, { className: 'inline w-4 h-4 mr-1' }),
            '색상 모드'
          ),
          React.createElement('button', {
            onClick: () => setVisualMode('both'),
            className: `flex-1 px-3 py-2 rounded text-sm font-medium ${visualMode === 'both' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-700'}`
          },
            React.createElement(Eye, { className: 'inline w-4 h-4 mr-1' }),
            '통합 모드'
          )
        ),
        
        React.createElement('div', { className: 'mt-2 text-sm text-gray-600 space-y-1' },
          visualMode === 'wheel' && React.createElement(React.Fragment, null,
            React.createElement('div', null, `🟢 녹색: A타입 바퀴 (${aWheels.length}개)`),
            React.createElement('div', null, `🔵 파랑: B타입 바퀴 (${bWheels.length}개)`),
            React.createElement('div', null, '🟡 노랑: 추적 중인 조각'),
            React.createElement('div', null, '⚪ 회색(반투명): 일반 조각')
          ),
          visualMode === 'color' && React.createElement(React.Fragment, null,
            React.createElement('div', null, '🔴 빨강(F): 정면 z=1 / 🟠 주황(B): 뒤 z=-1'),
            React.createElement('div', null, '⚪ 흰색(U): 위 y=1 / 🟡 노랑(D): 아래 y=-1'),
            React.createElement('div', null, '🔵 파랑(R): 오른쪽 x=1 / 🟢 초록(L): 왼쪽 x=-1')
          ),
          visualMode === 'both' && React.createElement('div', null, '각 면의 색상 + 바퀴/특수 조각은 불투명, 나머지는 반투명')
        )
      ),
      
      React.createElement('div', { className: 'space-y-4' },
        React.createElement('div', { className: 'bg-purple-50 p-4 rounded-lg' },
          React.createElement('h2', { className: 'font-semibold mb-3' }, '명령어 입력'),
          React.createElement('div', { className: 'space-y-2' },
            React.createElement('input', {
              type: 'text',
              value: commandInput,
              onChange: (e) => setCommandInput(e.target.value),
              placeholder: 'ex: U R B L',
              className: 'w-full px-3 py-2 border border-gray-300 rounded text-sm',
              onKeyPress: (e) => {
                if (e.key === 'Enter' && !isRotating) {
                  executeCommands(commandInput);
                  setCommandInput('');
                }
              }
            }),
            React.createElement('button', {
              onClick: () => {
                executeCommands(commandInput);
                setCommandInput('');
              },
              disabled: isRotating || !commandInput.trim(),
              className: 'w-full bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 disabled:opacity-50 text-sm'
            }, '실행'),
            React.createElement('div', { className: 'text-xs text-gray-600' }, '여러 명령어를 공백으로 구분 (예: U R B\')')
          )
        ),
        
        React.createElement('div', { className: 'bg-orange-50 p-4 rounded-lg' },
          React.createElement('h2', { className: 'font-semibold mb-3' }, 'A→B 바퀴 교체 알고리즘'),
          React.createElement('button', {
            onClick: runAlgorithmSearch,
            disabled: isSearching,
            className: 'w-full bg-orange-500 text-white px-4 py-2 rounded hover:bg-orange-600 disabled:opacity-50 text-sm mb-2 flex items-center justify-center gap-2'
          },
            React.createElement(Search, { className: 'w-4 h-4' }),
            isSearching ? '탐색 중...' : '최단 경로 탐색'
          ),
          searchResult && React.createElement('div', { className: 'text-sm space-y-2' },
            searchResult.success ? React.createElement(React.Fragment, null,
              React.createElement('div', { className: 'text-green-700 font-semibold' }, '✅ 해를 찾았습니다!'),
              React.createElement('div', null, `경로 길이: ${searchResult.length}회 회전`),
              React.createElement('div', null, `탐색 노드: ${searchResult.nodesExplored}개`),
              React.createElement('div', { className: 'bg-white p-2 rounded text-xs font-mono' }, searchResult.path.join(' ')),
              React.createElement('button', {
                onClick: executeSearchResult,
                disabled: isRotating,
                className: 'w-full bg-green-500 text-white px-3 py-2 rounded hover:bg-green-600 disabled:opacity-50 text-sm mt-2 flex items-center justify-center gap-2'
              },
                React.createElement(Play, { className: 'w-4 h-4' }),
                '알고리즘 실행'
              )
            ) : React.createElement(React.Fragment, null,
              React.createElement('div', { className: 'text-red-700 font-semibold' }, '❌ 해를 찾지 못했습니다'),
              React.createElement('div', null, searchResult.message),
              React.createElement('div', null, `탐색 노드: ${searchResult.nodesExplored}개`)
            )
          )
        ),
        
        React.createElement('div', { className: 'bg-blue-50 p-4 rounded-lg' },
          React.createElement('h2', { className: 'font-semibold mb-3' }, '로봇 회전 축 (4축)'),
          React.createElement('div', { className: 'grid grid-cols-2 gap-2' },
            ['U', 'R', 'L', 'B'].map(face =>
              React.createElement('div', { key: face, className: 'flex gap-1' },
                React.createElement('button', {
                  onClick: () => rotateFace(face, null, true),
                  disabled: isRotating,
                  className: 'flex-1 bg-blue-500 text-white px-2 py-2 rounded hover:bg-blue-600 text-xs disabled:opacity-50'
                },
                  face, ' ', React.createElement(RotateCw, { className: 'inline w-3 h-3' })
                ),
                React.createElement('button', {
                  onClick: () => rotateFace(face, null, false),
                  disabled: isRotating,
                  className: 'flex-1 bg-blue-400 text-white px-2 py-2 rounded hover:bg-blue-500 text-xs disabled:opacity-50'
                },
                  face, '\' ', React.createElement(RotateCcw, { className: 'inline w-3 h-3' })
                )
              )
            )
          )
        ),
        
        React.createElement('details', { className: 'bg-gray-100 p-3 rounded' },
          React.createElement('summary', { className: 'font-semibold cursor-pointer text-sm' }, '내부 동작용 (F, D)'),
          React.createElement('div', { className: 'grid grid-cols-2 gap-2 mt-2' },
            ['F', 'D'].map(face =>
              React.createElement('div', { key: face, className: 'flex gap-1' },
                React.createElement('button', {
                  onClick: () => rotateFace(face, null, true),
                  disabled: isRotating,
                  className: 'flex-1 bg-gray-500 text-white px-2 py-2 rounded hover:bg-gray-600 text-xs disabled:opacity-50'
                },
                  face, ' ', React.createElement(RotateCw, { className: 'inline w-3 h-3' })
                ),
                React.createElement('button', {
                  onClick: () => rotateFace(face, null, false),
                  disabled: isRotating,
                  className: 'flex-1 bg-gray-400 text-white px-2 py-2 rounded hover:bg-gray-500 text-xs disabled:opacity-50'
                },
                  face, '\' ', React.createElement(RotateCcw, { className: 'inline w-3 h-3' })
                )
              )
            )
          )
        ),
        
        React.createElement('button', {
          onClick: reset,
          className: 'w-full bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600 flex items-center justify-center gap-2'
        },
          React.createElement(RefreshCw, { className: 'w-4 h-4' }),
          '초기화'
        ),
        
        React.createElement('div', { className: 'bg-gray-50 p-4 rounded-lg' },
          React.createElement('h3', { className: 'font-semibold mb-2' }, '회전 기록'),
          React.createElement('div', { className: 'text-xs font-mono bg-white p-2 rounded min-h-[60px] max-h-[120px] overflow-y-auto' },
            history.join(' ') || '(없음)'
          ),
          React.createElement('div', { className: 'text-xs text-gray-600 mt-1' }, `총 ${history.length}회 회전`)
        ),
        
        React.createElement('div', { className: 'bg-green-50 p-4 rounded-lg' },
          React.createElement('h3', { className: 'font-semibold mb-2' }, '바퀴 조각 현황'),
          React.createElement('div', { className: 'text-sm space-y-2' },
            React.createElement('div', null,
              React.createElement('strong', null, 'A타입 (녹색): '), `${aWheels.length}개`,
              React.createElement('div', { className: 'text-xs text-gray-600 mt-1' },
                aWheels.map((w, i) => `(${w.x},${w.y},${w.z})`).join(', ')
              )
            ),
            React.createElement('div', null,
              React.createElement('strong', null, 'B타입 (파랑): '), `${bWheels.length}개`,
              React.createElement('div', { className: 'text-xs text-gray-600 mt-1' },
                bWheels.map((w, i) => `(${w.x},${w.y},${w.z})`).join(', ')
              )
            )
          )
        ),
        
        React.createElement('div', { className: 'bg-yellow-50 p-4 rounded-lg' },
          React.createElement('h3', { className: 'font-semibold mb-2' }, '조각 추적'),
          React.createElement('div', { className: 'text-sm space-y-2' },
            React.createElement('div', null,
              React.createElement('label', { className: 'block text-xs text-gray-600 mb-1' }, '추적할 조각 좌표:'),
              React.createElement('input', {
                type: 'text',
                value: trackedPiece,
                onChange: handleTrackedPieceChange,
                placeholder: '예: 0,1,-1',
                className: 'w-full px-2 py-1 border border-gray-300 rounded text-xs'
              })
            ),
            React.createElement('div', null,
              React.createElement('strong', null, '원래 위치: '), trackedPiece
            ),
            React.createElement('div', null,
              React.createElement('strong', null, '현재 위치: '),
              trackedPieceObj ? `(${trackedPieceObj.x}, ${trackedPieceObj.y}, ${trackedPieceObj.z})` : '찾을 수 없음'
            ),
            React.createElement('div', { className: 'text-xs text-gray-600' },
              trackedPieceObj && trackedPieceObj.originalKey === trackedPiece ? '✅ 원래 위치' : '⚠️ 이동됨'
            )
          )
        ),
        
        React.createElement('div', { className: 'bg-gray-100 p-3 rounded text-xs space-y-1' },
          React.createElement('strong', null, '회전 명령어:'),
          Object.entries(notations).map(([key, desc]) =>
            React.createElement('div', { key: key }, `${key}: ${desc}`)
          ),
          React.createElement('div', { className: 'mt-2 pt-2 border-t border-gray-300' }, '\' (프라임): 반시계 방향 회전')
        )
      )
    )
  );
};

export default CubeSimulator;
