import React from 'react';
import { BookOpen } from 'lucide-react';
import './PanelHelpButton.css';

interface PanelHelpButtonProps {
  panelKey: string;
  className?: string;
}

/**
 * Prominent "Hướng dẫn" button that opens the corresponding guide page in a new tab.
 * Place it inside a panel's header area.
 */
const PanelHelpButton: React.FC<PanelHelpButtonProps> = ({ panelKey, className = '' }) => {
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    window.open(`/guide/${panelKey}`, '_blank');
  };

  return (
    <button
      className={`panel-help-btn ${className}`}
      onClick={handleClick}
      title="Mở hướng dẫn sử dụng"
      aria-label="Mở hướng dẫn"
    >
      <BookOpen size={15} />
      <span>Hướng dẫn</span>
    </button>
  );
};

export default PanelHelpButton;
