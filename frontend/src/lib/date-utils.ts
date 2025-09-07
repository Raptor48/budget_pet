/**
 * Utility functions for safe date parsing and formatting
 * Handles both MM-DD-YYYY and YYYY-MM-DD formats for Safari compatibility
 */

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
      return new Date(dateString);
    }
    
    // Try parsing as MM-DD-YYYY format
    if (dateString.match(/^\d{2}-\d{2}-\d{4}$/)) {
      const [month, day, year] = dateString.split('-');
      // Create date in YYYY-MM-DD format for Safari compatibility
      const isoDate = `${year}-${month}-${day}`;
      return new Date(isoDate);
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
    const { format } = require('date-fns');
    return format(date, formatString);
  } catch (error) {
    console.warn('Failed to format date:', dateString, error);
    return dateString; // Return original string if formatting fails
  }
}
