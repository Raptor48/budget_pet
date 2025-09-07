/**
 * Utility functions for safe date parsing and formatting
 * Handles both MM-DD-YYYY and YYYY-MM-DD formats for Safari compatibility
 */

import { format } from 'date-fns';

/**
 * Safely parse a date string that could be in MM-DD-YYYY or YYYY-MM-DD format
 * @param dateString - Date string in either format
 * @returns Date object or null if invalid
 */
export function safeParseDate(dateString: string): Date | null {
  if (!dateString) return null;
  
  try {
    // Try parsing as YYYY-MM-DD first (ISO format)
    if (dateString.match(/^\d{4}-\d{2}-\d{2}$/)) {
      // Parse as local date to avoid timezone issues
      const [year, month, day] = dateString.split('-');
      return new Date(parseInt(year), parseInt(month) - 1, parseInt(day));
    }
    
    // Try parsing as MM-DD-YYYY format
    if (dateString.match(/^\d{2}-\d{2}-\d{4}$/)) {
      const [month, day, year] = dateString.split('-');
      // Create date in local timezone
      return new Date(parseInt(year), parseInt(month) - 1, parseInt(day));
    }
    
    // Fallback to direct parsing
    return new Date(dateString);
  } catch (error) {
    console.warn('Failed to parse date:', dateString, error);
    return null;
  }
}

/**
 * Format a date string safely for display
 * @param dateString - Date string in either format
 * @param formatString - Format string for date-fns
 * @returns Formatted date string or fallback
 */
export function safeFormatDate(dateString: string, formatString: string = "MMM dd, yyyy"): string {
  const date = safeParseDate(dateString);
  if (!date || isNaN(date.getTime())) {
    return dateString; // Return original string if parsing fails
  }
  
  try {
    return format(date, formatString);
  } catch (error) {
    console.warn('Failed to format date:', dateString, error);
    return dateString; // Return original string if formatting fails
  }
}
