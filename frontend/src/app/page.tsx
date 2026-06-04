'use client';

import React, { useState, useEffect } from 'react';
import Sidebar, { Session } from '@/components/Sidebar';
import ChatArea, { Message } from '@/components/ChatArea';
import ChatInput from '@/components/ChatInput';
import Modal from '@/components/Modal';
import { MoreVertical } from 'lucide-react';

export default function Home() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [isTyping, setIsTyping] = useState(false);
  const [activeModal, setActiveModal] = useState<'portfolio' | 'help' | 'settings' | null>(null);
  const [darkMode, setDarkMode] = useState(false);

  const starterQuestions = [
    "What is the exit load for HDFC Small Cap Fund?",
    "What is the minimum SIP amount for HDFC Nifty 50 Index Fund?",
    "Tell me about HDFC Mutual Fund as a fund house."
  ];

  // Initialize theme and sessions on mount
  useEffect(() => {
    // 1. Theme Check
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
      setDarkMode(true);
      document.body.classList.add('dark-mode');
    }

    // 2. Sessions Check
    const savedSessions = localStorage.getItem('hdfc_chat_sessions');
    const savedActiveId = localStorage.getItem('hdfc_active_session_id');

    if (savedSessions) {
      const parsed = JSON.parse(savedSessions);
      setSessions(parsed);
      if (savedActiveId && parsed.some((s: any) => s.id === savedActiveId)) {
        setActiveSessionId(savedActiveId);
      } else if (parsed.length > 0) {
        setActiveSessionId(parsed[0].id);
      }
    } else {
      // Create initial welcome session
      const defaultId = Date.now().toString();
      const defaultSession: Session = {
        id: defaultId,
        title: 'New Chat',
        messages: [
          {
            id: '1',
            role: 'assistant' as const,
            content: 'Hello! I am the HDFC Mutual Fund FAQ Assistant. I can help answer objective, factual questions about specific HDFC Mutual Fund schemes in scope (e.g., exit loads, expense ratios, minimum investment limits, and general fund facts).\n\n*Please note: I cannot provide investment advice, scheme recommendations, return projections, or performance comparisons.*',
          }
        ]
      };
      setSessions([defaultSession]);
      setActiveSessionId(defaultId);
      localStorage.setItem('hdfc_chat_sessions', JSON.stringify([defaultSession]));
      localStorage.setItem('hdfc_active_session_id', defaultId);
    }
  }, []);

  const updateSessions = (newSessions: Session[]) => {
    setSessions(newSessions);
    localStorage.setItem('hdfc_chat_sessions', JSON.stringify(newSessions));
  };

  const selectActiveSession = (id: string) => {
    setActiveSessionId(id);
    localStorage.setItem('hdfc_active_session_id', id);
  };

  const handleNewChat = () => {
    const newId = Date.now().toString();
    const newSession: Session = {
      id: newId,
      title: 'New Chat',
      messages: [
        {
          id: '1',
          role: 'assistant' as const,
          content: 'Hello! I am the HDFC Mutual Fund FAQ Assistant. I can help answer objective, factual questions about specific HDFC Mutual Fund schemes in scope (e.g., exit loads, expense ratios, minimum investment limits, and general fund facts).\n\n*Please note: I cannot provide investment advice, scheme recommendations, return projections, or performance comparisons.*',
        }
      ]
    };
    const updated = [newSession, ...sessions];
    updateSessions(updated);
    selectActiveSession(newId);
  };

  const handleSendMessage = async (content: string) => {
    if (!activeSessionId) return;
    
    const activeSession = sessions.find(s => s.id === activeSessionId);
    if (!activeSession) return;

    const newUserMsg = { id: Date.now().toString(), role: 'user' as const, content };
    
    // Append user message
    const updatedMessages = [...activeSession.messages, newUserMsg];
    
    // Auto title update if this was a new chat
    let newTitle = activeSession.title;
    if (activeSession.title === 'New Chat') {
      newTitle = content.length > 25 ? content.slice(0, 22) + '...' : content;
    }

    const updatedSession = {
      ...activeSession,
      title: newTitle,
      messages: updatedMessages
    };

    const updatedSessions = sessions.map(s => s.id === activeSessionId ? updatedSession : s);
    updateSessions(updatedSessions);
    setIsTyping(true);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: content }),
      });

      if (!response.ok) {
        throw new Error('Failed to fetch response');
      }

      const data = await response.json();
      
      const assistantMsg = {
        id: (Date.now() + 1).toString(),
        role: 'assistant' as const,
        content: data.answer,
        source_url: data.source_url,
        last_updated: data.last_updated,
      };

      const finalMessages = [...updatedMessages, assistantMsg];
      const finalSession = {
        ...updatedSession,
        messages: finalMessages
      };

      const finalSessions = sessions.map(s => s.id === activeSessionId ? finalSession : s);
      updateSessions(finalSessions);
    } catch (error) {
      console.error('Error fetching from API:', error);
      const errorMsg = {
        id: (Date.now() + 1).toString(),
        role: 'assistant' as const,
        content: "Sorry, I am currently unable to connect to the backend server. Please try again later.",
      };
      const finalMessages = [...updatedMessages, errorMsg];
      const finalSession = {
        ...updatedSession,
        messages: finalMessages
      };
      const finalSessions = sessions.map(s => s.id === activeSessionId ? finalSession : s);
      updateSessions(finalSessions);
    } finally {
      setIsTyping(false);
    }
  };

  const handleToggleDarkMode = () => {
    const nextMode = !darkMode;
    setDarkMode(nextMode);
    if (nextMode) {
      document.body.classList.add('dark-mode');
      localStorage.setItem('theme', 'dark');
    } else {
      document.body.classList.remove('dark-mode');
      localStorage.setItem('theme', 'light');
    }
  };

  const handleOpenModal = (modalType: 'portfolio' | 'help' | 'settings') => {
    setActiveModal(modalType);
  };

  const currentSession = sessions.find(s => s.id === activeSessionId) || sessions[0];
  const messages = currentSession ? currentSession.messages : [];
  const hasUserMessages = messages.some(msg => msg.role === 'user');

  return (
    <div className="app-container">
      <Sidebar 
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={selectActiveSession}
        onNewChat={handleNewChat}
        onOpenModal={handleOpenModal}
      />
      <div className="chat-layout">
        <header className="chat-header">
          <div className="chat-header-title">
            {currentSession ? currentSession.title : "HDFC MF FAQ Assistant"}
          </div>
          <button className="icon-btn">
            <MoreVertical size={20} />
          </button>
        </header>

        <div className="disclaimer-banner">
          <span className="banner-icon">⚠️</span>
          <span className="banner-text">
            <strong>Facts-only. No investment advice.</strong> I answer objective questions using official HDFC MF details.
          </span>
        </div>
        
        <ChatArea messages={messages} isTyping={isTyping} />

        {!hasUserMessages && (
          <div className="quick-starters-container">
            <div className="quick-starters-title">Frequently Asked Questions</div>
            <div className="starter-questions">
              {starterQuestions.map((q, idx) => (
                <button
                  key={idx}
                  className="starter-card"
                  onClick={() => handleSendMessage(q)}
                  disabled={isTyping}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        
        <ChatInput onSend={handleSendMessage} disabled={isTyping} />
      </div>

      {/* Modals */}
      <Modal
        isOpen={activeModal === 'portfolio'}
        onClose={() => setActiveModal(null)}
        title="Portfolio Analyzer"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <p>
            The <strong>Portfolio Analyzer</strong> is a tool to evaluate your asset allocation, diversification, and potential risks.
          </p>
          <div style={{ padding: '16px', backgroundColor: 'rgba(237, 35, 42, 0.08)', borderLeft: '4px solid var(--secondary-color)', borderRadius: '6px', fontSize: '14px' }}>
            <strong>⚠️ SEBI Compliance Notice:</strong>
            <p style={{ marginTop: '8px' }}>
              To comply with SEBI regulations regarding investment advice, this facts-only assistant does not provide automated portfolio allocation advice, scheme recommendations, or personalized planning.
            </p>
          </div>
          <p>
            Please use official Groww tools or consult a SEBI-registered investment advisor (RIA) for personalized portfolio reviews.
          </p>
        </div>
      </Modal>

      <Modal
        isOpen={activeModal === 'help'}
        onClose={() => setActiveModal(null)}
        title="Help & FAQ"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', fontSize: '14px' }}>
          <p>
            This assistant is designed to answer objective, factual questions about specific <strong>HDFC Mutual Fund</strong> schemes in scope.
          </p>
          <div>
            <strong>Supported Schemes:</strong>
            <ul style={{ paddingLeft: '20px', marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <li>HDFC Silver ETF Fund of Fund</li>
              <li>HDFC Mid-Cap Opportunities Fund</li>
              <li>HDFC Equity Fund</li>
              <li>HDFC Small Cap Fund</li>
              <li>HDFC Defence Fund</li>
              <li>HDFC Gold ETF Fund of Fund</li>
              <li>HDFC Nifty 50 Index Fund</li>
            </ul>
          </div>
          <div>
            <strong>Example Questions You Can Ask:</strong>
            <ul style={{ paddingLeft: '20px', marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <li><em>"What is the exit load of HDFC Small Cap Fund?"</em></li>
              <li><em>"What is the minimum SIP amount for HDFC Defence Fund?"</em></li>
              <li><em>"What benchmark index does HDFC Nifty 50 Index Fund track?"</em></li>
            </ul>
          </div>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Note: Past returns, performance comparisons, and advisory queries (e.g. "which is the best fund") are strictly out of scope and will be refused by the system.
          </p>
        </div>
      </Modal>

      <Modal
        isOpen={activeModal === 'settings'}
        onClose={() => setActiveModal(null)}
        title="Settings"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="toggle-container">
            <span className="toggle-label">Dark Mode Theme</span>
            <label className="toggle-switch">
              <input 
                type="checkbox" 
                checked={darkMode} 
                onChange={handleToggleDarkMode}
              />
              <span className="toggle-slider"></span>
            </label>
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            Toggle the theme to switch between dark and light modes.
          </p>
        </div>
      </Modal>
    </div>
  );
}
