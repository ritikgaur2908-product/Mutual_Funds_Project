'use client';

import React from 'react';

export type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  source_url?: string;
  last_updated?: string;
};

interface ChatAreaProps {
  messages: Message[];
  isTyping?: boolean;
}

export default function ChatArea({ messages, isTyping }: ChatAreaProps) {
  return (
    <div className="chat-area">
      {messages.map((msg) => (
        <div key={msg.id} className={`message-container ${msg.role}`}>
          <div className={`message-avatar ${msg.role}`}>
            {msg.role === 'assistant' ? 'H' : 'U'}
          </div>
          <div className="message-bubble">
            <div className="message-text">{msg.content}</div>
            
            {msg.role === 'assistant' && (msg.source_url || msg.last_updated) && (
              <div className="message-metadata">
                {msg.source_url && msg.source_url !== 'N/A' && (
                  <div className="metadata-row source">
                    <span className="metadata-label">Source:</span>{' '}
                    <a 
                      href={msg.source_url} 
                      target="_blank" 
                      rel="noopener noreferrer" 
                      className="source-link"
                    >
                      {msg.source_url}
                    </a>
                  </div>
                )}
                {msg.last_updated && msg.last_updated !== 'N/A' && (
                  <div className="metadata-row updated">
                    <span className="metadata-label">Last Updated:</span>{' '}
                    <span className="updated-date">{msg.last_updated}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ))}
      
      {isTyping && (
        <div className="message-container assistant typing">
          <div className="message-avatar assistant">H</div>
          <div className="message-bubble typing-bubble">
            <div className="typing-indicator">
              <span className="typing-dot"></span>
              <span className="typing-dot"></span>
              <span className="typing-dot"></span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
