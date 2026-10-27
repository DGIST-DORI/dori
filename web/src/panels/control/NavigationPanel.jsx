import './NavigationPanel.css';

export default function NavigationPanel() {
  return <section className="navigation-panel">
    <p>지도에서 초기 위치와 목적지를 확인한 뒤 주행을 시작하세요. 웹과 음성 안내는 같은 주행 상태를 사용합니다.</p>
    <iframe title="DORI 실시간 지도 및 주행 제어" src="/navigation/" />
  </section>;
}
