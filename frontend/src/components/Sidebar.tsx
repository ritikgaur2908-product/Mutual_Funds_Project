'use client';

import React from 'react';
import { MessageSquare, Settings, HelpCircle, Plus, PieChart } from 'lucide-react';
import { Message } from './ChatArea';

export type Session = {
  id: string;
  title: string;
  messages: Message[];
};

interface SidebarProps {
  sessions: Session[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onOpenModal: (modalType: 'portfolio' | 'help' | 'settings') => void;
}

export default function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onOpenModal,
}: SidebarProps) {
  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="brand-logo">H</div>
        <div>
          <div className="brand-title">HDFC Assistant</div>
          <div className="brand-subtitle">Mutual Fund FAQ Assistant</div>
        </div>
      </div>
      
      <div className="sidebar-content">
        <a 
          href="#" 
          onClick={(e) => {
            e.preventDefault();
            onNewChat();
          }}
          className="history-item" 
          style={{ marginBottom: '24px', backgroundColor: 'var(--primary-color)', color: 'white' }}
        >
          <Plus size={18} />
          <span className="history-item-text">New Chat</span>
        </a>

        <div className="sidebar-section-title">Recent Chats</div>
        {sessions.map((item) => (
          <a 
            key={item.id} 
            href="#" 
            onClick={(e) => {
              e.preventDefault();
              onSelectSession(item.id);
            }}
            className={`history-item ${item.id === activeSessionId ? 'active' : ''}`}
          >
            <MessageSquare size={16} className="icon" />
            <span className="history-item-text">{item.title}</span>
          </a>
        ))}
        {sessions.length === 0 && (
          <div style={{ padding: '0 8px', fontSize: '13px', color: 'var(--text-muted)' }}>
            No recent chats
          </div>
        )}
        
        <div className="sidebar-section-title" style={{ marginTop: '24px' }}>Quick Tools</div>
        <a 
          href="#" 
          onClick={(e) => {
            e.preventDefault();
            onOpenModal('portfolio');
          }}
          className="history-item"
        >
          <PieChart size={16} className="icon" />
          <span className="history-item-text">Portfolio Analyzer</span>
        </a>
      </div>
      
      <div style={{ padding: '16px', borderTop: '1px solid var(--border-color)' }}>
        <a 
          href="#" 
          onClick={(e) => {
            e.preventDefault();
            onOpenModal('help');
          }}
          className="history-item"
        >
          <HelpCircle size={16} className="icon" />
          <span className="history-item-text">Help & FAQ</span>
        </a>
        <a 
          href="#" 
          onClick={(e) => {
            e.preventDefault();
            onOpenModal('settings');
          }}
          className="history-item"
        >
          <Settings size={16} className="icon" />
          <span className="history-item-text">Settings</span>
        </a>
      </div>
    </div>
  );
}
