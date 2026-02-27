"""
Enhanced progress UI components with pie charts and phase indicators.
"""

import tkinter as tk
from tkinter import ttk
import math
import time
from typing import Optional


class PieProgressWidget(tk.Canvas):
    """A pie chart progress indicator widget."""
    
    def __init__(self, parent, size=60, bg_color="#f0f0f0", fill_color="#4CAF50", 
                 text_color="#333", **kwargs):
        super().__init__(parent, width=size, height=size, bg=bg_color, 
                        highlightthickness=0, **kwargs)
        self.size = size
        self.bg_color = bg_color
        self.fill_color = fill_color
        self.text_color = text_color
        self.progress = 0.0
        self.center = size // 2
        self.radius = (size - 8) // 2
        
        # Create pie chart elements
        self.bg_circle = None
        self.progress_arc = None
        self.progress_text = None
        self.phase_text = None
        
        self.draw_background()
        
    def draw_background(self):
        """Draw the background circle."""
        margin = 4
        self.bg_circle = self.create_oval(
            margin, margin, 
            self.size - margin, self.size - margin,
            fill="#e0e0e0", outline="#d0d0d0", width=1
        )
        
    def set_progress(self, progress: float, phase_name: str = "", show_percentage: bool = True):
        """Update the progress (0.0 to 1.0) and phase name."""
        self.progress = max(0.0, min(1.0, progress))
        
        # Clear existing progress elements
        if self.progress_arc:
            self.delete(self.progress_arc)
        if self.progress_text:
            self.delete(self.progress_text)
        if self.phase_text:
            self.delete(self.phase_text)
        
        # Draw progress arc
        if self.progress > 0:
            margin = 4
            extent = 360 * self.progress
            self.progress_arc = self.create_arc(
                margin, margin,
                self.size - margin, self.size - margin,
                start=90, extent=-extent,
                fill=self.fill_color, outline=self.fill_color, width=2
            )
        
        # Draw progress text
        if show_percentage:
            percentage = int(self.progress * 100)
            self.progress_text = self.create_text(
                self.center, self.center - 4,
                text=f"{percentage}%",
                fill=self.text_color, font=("Arial", 10, "bold")
            )
        
        # Draw phase name (abbreviated if too long)
        if phase_name:
            if len(phase_name) > 12:
                phase_name = phase_name[:9] + "..."
            self.phase_text = self.create_text(
                self.center, self.center + 8,
                text=phase_name,
                fill=self.text_color, font=("Arial", 7)
            )


class CountdownTimer(tk.Label):
    """A countdown timer widget showing remaining time."""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.remaining_seconds = 0
        self.last_update = time.time()
        self.timer_job = None
        
    def set_remaining(self, seconds: float):
        """Set the remaining time in seconds."""
        self.remaining_seconds = max(0, seconds)
        self.last_update = time.time()
        self.update_display()
        
        # Cancel existing timer
        if self.timer_job:
            self.after_cancel(self.timer_job)
        
        # Start countdown if time remaining
        if self.remaining_seconds > 0:
            self.start_countdown()
    
    def update_display(self):
        """Update the display text."""
        if self.remaining_seconds <= 0:
            self.config(text="Complete!")
        elif self.remaining_seconds < 60:
            self.config(text=f"{int(self.remaining_seconds)}s remaining")
        elif self.remaining_seconds < 3600:
            minutes = int(self.remaining_seconds // 60)
            seconds = int(self.remaining_seconds % 60)
            self.config(text=f"{minutes}m {seconds}s remaining")
        else:
            hours = int(self.remaining_seconds // 3600)
            minutes = int((self.remaining_seconds % 3600) // 60)
            self.config(text=f"{hours}h {minutes}m remaining")
    
    def start_countdown(self):
        """Start the countdown timer."""
        if self.remaining_seconds > 0:
            self.remaining_seconds = max(0, self.remaining_seconds - 1)
            self.update_display()
            self.timer_job = self.after(1000, self.start_countdown)


class PhaseIndicator(tk.Frame):
    """Shows current phase with visual indicator."""
    
    def __init__(self, parent, phases=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.phases = phases or []
        self.current_phase_idx = 0
        self.phase_labels = []
        self.setup_ui()
        
    def setup_ui(self):
        """Set up the phase indicator UI."""
        for i, phase in enumerate(self.phases):
            # Create phase dot
            dot = tk.Label(self, text="●", font=("Arial", 8), fg="#ccc")
            dot.grid(row=0, column=i*2, padx=2)
            
            # Create phase label
            label = tk.Label(self, text=phase[:8], font=("Arial", 7), fg="#666")
            label.grid(row=1, column=i*2, padx=2)
            
            self.phase_labels.append((dot, label))
            
            # Add separator line (except for last item)
            if i < len(self.phases) - 1:
                sep = tk.Label(self, text="—", font=("Arial", 6), fg="#ddd")
                sep.grid(row=0, column=i*2+1, padx=1)
    
    def set_current_phase(self, phase_name: str):
        """Set the current active phase."""
        # Find phase index
        phase_idx = -1
        for i, phase in enumerate(self.phases):
            if phase.lower() in phase_name.lower():
                phase_idx = i
                break
        
        if phase_idx >= 0:
            self.current_phase_idx = phase_idx
        
        # Update visual indicators
        for i, (dot, label) in enumerate(self.phase_labels):
            if i < self.current_phase_idx:
                # Completed phase
                dot.config(fg="#4CAF50")
                label.config(fg="#333")
            elif i == self.current_phase_idx:
                # Current phase
                dot.config(fg="#2196F3")
                label.config(fg="#000", font=("Arial", 7, "bold"))
            else:
                # Upcoming phase
                dot.config(fg="#ccc")
                label.config(fg="#666")


class EnhancedProgressFrame(tk.Frame):
    """Complete enhanced progress frame with all components."""
    
    PHASES = [
        "Preflight", "Rules", "Analysis", "AI Extract", 
        "Validation", "Merging", "Track Changes"
    ]
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.setup_ui()
        
    def setup_ui(self):
        """Set up the complete progress UI."""
        # Main info frame
        info_frame = tk.Frame(self)
        info_frame.pack(fill=tk.X, pady=5)
        
        # Left side - pie chart and timer
        left_frame = tk.Frame(info_frame)
        left_frame.pack(side=tk.LEFT, padx=10)
        
        # Pie chart
        self.pie_chart = PieProgressWidget(left_frame, size=50)
        self.pie_chart.pack()
        
        # Timer below pie chart
        self.countdown = CountdownTimer(left_frame, font=("Arial", 9), fg="#666")
        self.countdown.pack(pady=2)
        
        # Right side - phase info
        right_frame = tk.Frame(info_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # Phase name and message
        self.phase_label = tk.Label(right_frame, text="Ready", 
                                   font=("Arial", 12, "bold"), anchor=tk.W)
        self.phase_label.pack(fill=tk.X)
        
        self.message_label = tk.Label(right_frame, text="Select a document to begin", 
                                     font=("Arial", 9), fg="#666", anchor=tk.W)
        self.message_label.pack(fill=tk.X)
        
        # Overall progress bar
        progress_frame = tk.Frame(self)
        progress_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(progress_frame, text="Overall Progress:", font=("Arial", 8), fg="#666").pack(anchor=tk.W)
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=2)
        
        # Phase indicator
        self.phase_indicator = PhaseIndicator(self, phases=self.PHASES)
        self.phase_indicator.pack(fill=tk.X, pady=5)
        
    def update_progress(self, phase_progress: float, overall_progress: float, 
                       phase_name: str, estimated_remaining: float, message: str = ""):
        """Update all progress components."""
        # Update pie chart
        self.pie_chart.set_progress(phase_progress, phase_name[:8])
        
        # Update labels
        self.phase_label.config(text=phase_name)
        self.message_label.config(text=message or "Processing...")
        
        # Update progress bar (convert to percentage)
        self.progress_bar['value'] = overall_progress * 100
        
        # Update countdown timer
        self.countdown.set_remaining(estimated_remaining)
        
        # Update phase indicator
        self.phase_indicator.set_current_phase(phase_name)
        
    def reset(self):
        """Reset all progress indicators."""
        self.pie_chart.set_progress(0.0, "")
        self.phase_label.config(text="Ready")
        self.message_label.config(text="Select a document to begin")
        self.progress_bar['value'] = 0
        self.countdown.config(text="")
        self.phase_indicator.current_phase_idx = 0
        
        # Reset phase indicators
        for dot, label in self.phase_indicator.phase_labels:
            dot.config(fg="#ccc")
            label.config(fg="#666", font=("Arial", 7))