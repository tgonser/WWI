import folium
import json
import pandas as pd
from datetime import datetime
import os
from flask import Flask, render_template_string, jsonify, request
import webbrowser
from threading import Timer

class LocationMapViewer:
    """Interactive map viewer for processed location data"""
    
    def __init__(self, data_source=None):
        self.data_source = data_source
        self.map_data = None
        self.app = Flask(__name__)
        self.setup_routes()
    
    def load_data(self, file_path):
        """Load location data from parsed JSON file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both wrapped and direct array formats
            if isinstance(data, dict):
                if '_metadata' in data:
                    # Custom parsed format
                    entries = data.get('timelineObjects', [])
                    metadata = data.get('_metadata', {})
                elif 'timelineObjects' in data:
                    # Standard wrapped format
                    entries = data['timelineObjects']
                    metadata = {}
                else:
                    entries = [data]
                    metadata = {}
            else:
                # Direct array format
                entries = data
                metadata = {}
            
            self.map_data = {
                'entries': entries,
                'metadata': metadata,
                'total_points': len(entries)
            }
            
            print(f"Loaded {len(entries)} location entries for mapping")
            return True
            
        except Exception as e:
            print(f"Error loading data: {e}")
            return False
    
    def extract_coordinates(self):
        """Extract coordinate points from location data with fixed timeline processing"""
        points = []
        
        if not self.map_data:
            return points
        
        # First, separate timeline entries from visit/activity entries
        timeline_entries = []
        discrete_entries = []
        
        for entry in self.map_data['entries']:
            if 'timelinePath' in entry:
                timeline_entries.append(entry)
            else:
                discrete_entries.append(entry)
        
        # Process discrete entries (visits and activities) first
        discrete_points = []
        for entry in discrete_entries:
            try:
                entry_points = []
                
                # Handle visits
                if 'visit' in entry:
                    visit = entry['visit']
                    if 'topCandidate' in visit and 'placeLocation' in visit['topCandidate']:
                        coord_str = visit['topCandidate']['placeLocation']
                        coords = self.parse_coordinates(coord_str)
                        if coords:
                            entry_points.append({
                                'lat': coords[0],
                                'lon': coords[1],
                                'type': 'visit',
                                'semantic_type': visit['topCandidate'].get('semanticType', 'Unknown'),
                                'start_time': entry.get('startTime', ''),
                                'end_time': entry.get('endTime', ''),
                                'probability': visit.get('probability', '0'),
                                'entry_start_time': entry.get('startTime', ''),  # Keep for sorting
                                'is_timeline': False
                            })
                
                # Handle activities (start and end points)
                elif 'activity' in entry:
                    activity = entry['activity']
                    
                    # Start point
                    start_coords = self.parse_coordinates(activity.get('start', ''))
                    if start_coords:
                        entry_points.append({
                            'lat': start_coords[0],
                            'lon': start_coords[1],
                            'type': 'activity_start',
                            'activity_type': activity.get('topCandidate', {}).get('type', 'unknown'),
                            'start_time': entry.get('startTime', ''),
                            'distance': activity.get('distanceMeters', '0'),
                            'entry_start_time': entry.get('startTime', ''),
                            'is_timeline': False
                        })
                    
                    # End point
                    end_coords = self.parse_coordinates(activity.get('end', ''))
                    if end_coords:
                        entry_points.append({
                            'lat': end_coords[0],
                            'lon': end_coords[1],
                            'type': 'activity_end',
                            'activity_type': activity.get('topCandidate', {}).get('type', 'unknown'),
                            'end_time': entry.get('endTime', ''),
                            'distance': activity.get('distanceMeters', '0'),
                            'entry_start_time': entry.get('startTime', ''),
                            'is_timeline': False
                        })
                
                discrete_points.extend(entry_points)
                
            except Exception as e:
                print(f"Error processing discrete entry: {e}")
                continue
        
        # Sort discrete points by their entry start time
        discrete_points.sort(key=lambda x: x['entry_start_time'])
        
        # Now process timeline entries and insert them in appropriate positions
        final_points = []
        
        for discrete_point in discrete_points:
            final_points.append(discrete_point)
            
            # Check if there are any timeline entries that should be inserted after this discrete point
            discrete_time = discrete_point['entry_start_time']
            
            # Find timeline entries that logically belong after this discrete point
            for timeline_entry in timeline_entries:
                timeline_start = timeline_entry.get('startTime', '')
                
                # Insert timeline points if their start time is close to this discrete point
                # This helps maintain logical geographic flow
                try:
                    import pandas as pd
                    discrete_dt = pd.to_datetime(discrete_time, utc=True)
                    timeline_dt = pd.to_datetime(timeline_start, utc=True)
                    
                    # If timeline starts within 4 hours of this discrete point, process it
                    time_diff = abs((timeline_dt - discrete_dt).total_seconds())
                    if time_diff <= 4 * 3600:  # 4 hours
                        timeline_points = self.process_single_timeline_entry(timeline_entry)
                        
                        # Add timeline points with proper sequencing
                        for tl_point in timeline_points:
                            tl_point['follows_discrete_point'] = len(final_points) - 1
                            final_points.append(tl_point)
                        
                        # Remove processed timeline entry
                        timeline_entries.remove(timeline_entry)
                        break
                        
                except Exception as e:
                    print(f"Error processing timeline timing: {e}")
                    continue
        
        # Add any remaining timeline entries that weren't inserted
        for timeline_entry in timeline_entries:
            timeline_points = self.process_single_timeline_entry(timeline_entry)
            final_points.extend(timeline_points)
        
        return final_points
    
    def process_single_timeline_entry(self, entry):
        """Process a single timeline entry and return its points"""
        points = []
        
        try:
            timeline_path = entry.get('timelinePath', [])
            if not timeline_path:
                return points
            
            # Get date range from metadata instead of hardcoding
            from_dt = None
            to_dt = None
            
            if self.map_data and 'metadata' in self.map_data:
                metadata = self.map_data['metadata']
                date_range = metadata.get('dateRange', {})
                if date_range:
                    try:
                        from_dt = pd.to_datetime(date_range.get('from'), utc=True)
                        to_dt = pd.to_datetime(date_range.get('to'), utc=True) + pd.Timedelta(days=1)
                    except:
                        pass
            
            # Fallback to a wide date range if no metadata available
            if not from_dt or not to_dt:
                from_dt = pd.to_datetime('2020-01-01', utc=True)
                to_dt = pd.to_datetime('2030-12-31', utc=True)
            
            # Filter and process points within the timeline entry
            for point in timeline_path:
                # Calculate when this specific point actually occurred
                point_time = self.get_point_timestamp(
                    entry['startTime'], 
                    point.get('durationMinutesOffsetFromStartTime', '0')
                )
                
                # Only include points that fall within the date range
                if point_time and from_dt <= point_time < to_dt:
                    coords = self.parse_coordinates(point.get('point'))
                    if coords:
                        points.append({
                            'lat': coords[0],
                            'lon': coords[1],
                            'type': 'timeline_point',
                            'mode': point.get('mode', 'unknown'),
                            'start_time': entry.get('startTime', ''),
                            'offset': point.get('durationMinutesOffsetFromStartTime', '0'),
                            'actual_time': point_time.isoformat(),
                            'entry_start_time': entry.get('startTime', ''),
                            'is_timeline': True
                        })
            
            # Sort timeline points by their actual calculated time
            points.sort(key=lambda x: x['actual_time'])
            
        except Exception as e:
            print(f"Error processing timeline entry: {e}")
        
        return points
    
    def get_point_timestamp(self, entry_start_time, duration_offset_minutes):
        """Calculate the actual timestamp for a timeline point"""
        try:
            import pandas as pd
            start_dt = pd.to_datetime(entry_start_time, utc=True)
            if not start_dt:
                return None
            offset_minutes = int(duration_offset_minutes) if duration_offset_minutes else 0
            return start_dt + pd.Timedelta(minutes=offset_minutes)
        except:
            return None
    
    def parse_coordinates(self, coord_str):
        """Parse coordinates from geo: string format"""
        if not coord_str or not isinstance(coord_str, str):
            return None
        
        if coord_str.startswith('geo:'):
            try:
                coords = coord_str.replace('geo:', '').split(',')
                if len(coords) == 2:
                    lat, lon = float(coords[0]), float(coords[1])
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        return lat, lon
            except:
                pass
        
        return None
    
    def create_map(self, center_lat=None, center_lon=None, zoom_level=10):
        """Create map with selective line drawing - only connect related points"""
        points = self.extract_coordinates()
        
        if not points:
            print("No valid coordinates found in data")
            return None
        
        # Calculate center if not provided
        if center_lat is None or center_lon is None:
            center_lat = sum(p['lat'] for p in points) / len(points)
            center_lon = sum(p['lon'] for p in points) / len(points)
        
        # Create base map
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=zoom_level,
            tiles='OpenStreetMap'
        )
        
        # Color coding for different point types
        colors = {
            'visit': 'red',
            'activity_start': 'green', 
            'activity_end': 'blue',
            'timeline_point': 'orange'
        }
        
        # Sort ALL points chronologically
        all_points_chronological = self.sort_all_points_chronologically(points)
        
        # Draw lines SELECTIVELY - only between points that should be connected
        self.draw_selective_lines(m, all_points_chronological)
        
        # Add markers for all points
        self.add_clean_markers(m, all_points_chronological, colors)
        
        # Simple legend
        legend_html = '''
        <div style="position: fixed; 
                    bottom: 50px; left: 50px; width: 180px; height: 120px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px; border-radius: 5px;">
        <p><b>Location Tracking</b></p>
        <p><span style="color:red; font-size:16px;">●</span> Visits (numbered)</p>
        <p><span style="color:green; font-size:14px;">●</span> Activity Start</p>
        <p><span style="color:blue; font-size:14px;">●</span> Activity End</p>
        <p><span style="color:orange; font-size:10px;">●</span> Route Points</p>
        <hr style="margin: 8px 0;">
        <p><span style="color:#1976D2; font-size:16px;">━</span> Connected Routes</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
    
    def draw_selective_lines(self, map_obj, all_points):
        """Draw lines between logically connected points AND bridge reasonable gaps"""
        
        # Group points by their source entry
        entries_with_points = self.group_points_by_entry(all_points)
        
        # Draw lines within each entry group
        for entry_info in entries_with_points:
            entry_points = entry_info['points']
            entry_type = entry_info['type']
            
            if len(entry_points) > 1:
                if entry_type == 'timelinePath':
                    # Draw continuous line through timeline path points
                    path_coords = [[p['lat'], p['lon']] for p in entry_points]
                    folium.PolyLine(
                        locations=path_coords,
                        color='#1976D2',
                        weight=3,
                        opacity=0.7,
                        popup=f'Timeline path ({len(entry_points)} points)'
                    ).add_to(map_obj)
                    
                # Remove activity lines - activities are just markers, not connected paths
        
        # NEW: Add intelligent gap filling between timeline segments
        self.add_intelligent_gap_filling(map_obj, entries_with_points)
    
    def add_intelligent_gap_filling(self, map_obj, entries_with_points):
        """Add lines to bridge reasonable gaps between timeline segments"""
        
        # Get all timeline entries sorted by time
        timeline_entries = [e for e in entries_with_points if e['type'] == 'timelinePath']
        
        # Sort timeline entries by their first point's time
        timeline_entries.sort(key=lambda x: x['points'][0].get('sort_time', ''))
        
        # Connect timeline segments that should be bridged
        for i in range(len(timeline_entries) - 1):
            current_entry = timeline_entries[i]
            next_entry = timeline_entries[i + 1]
            
            # Get the last point of current entry and first point of next entry
            last_point = current_entry['points'][-1]
            first_point = next_entry['points'][0]
            
            # Check if we should bridge this gap
            if self.should_bridge_gap(last_point, first_point):
                # Draw a bridging line
                folium.PolyLine(
                    locations=[[last_point['lat'], last_point['lon']], 
                             [first_point['lat'], first_point['lon']]],
                    color='#1976D2',
                    weight=2,
                    opacity=0.5,
                    dashArray='5, 5',  # Dashed line to show it's inferred
                    popup='Inferred connection between timeline segments'
                ).add_to(map_obj)
    
    def should_bridge_gap(self, point1, point2):
        """Determine if we should bridge the gap between two timeline segments"""
        try:
            import pandas as pd
            
            # Get timestamps
            time1 = pd.to_datetime(point1.get('actual_time', point1.get('sort_time', '')), utc=True)
            time2 = pd.to_datetime(point2.get('actual_time', point2.get('sort_time', '')), utc=True)
            
            # Calculate time gap
            time_gap = (time2 - time1).total_seconds()
            
            # Calculate distance
            distance = self.calculate_distance(
                (point1['lat'], point1['lon']),
                (point2['lat'], point2['lon'])
            )
            
            # Bridge if:
            # 1. Time gap is reasonable (less than 4 hours)
            # 2. Distance is reasonable (less than 200km)
            # 3. Points are in chronological order
            if (time_gap > 0 and  # Chronological order
                time_gap < 4 * 3600 and  # Less than 4 hours
                distance < 200000):  # Less than 200km
                return True
            
            return False
            
        except Exception as e:
            print(f"Error checking gap bridging: {e}")
            return False
    
    @staticmethod
    def calculate_distance(coords1, coords2):
        """Calculate distance between two coordinate points in meters."""
        from math import radians, cos, sin, asin, sqrt
        
        lat1, lon1 = coords1
        lat2, lon2 = coords2
        
        # Convert to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        r = 6371  # Earth radius in kilometers
        return c * r * 1000  # Convert to meters
    
    def group_points_by_entry(self, all_points):
        """Group points by their original entry source"""
        entries = {}
        
        for point in all_points:
            entry_key = point.get('entry_start_time', 'unknown')
            point_type = point['type']
            
            # Create a unique key for each source entry
            if point.get('is_timeline', False):
                # Timeline points belong to timeline entries
                group_key = f"timeline_{entry_key}"
                group_type = 'timelinePath'
            elif point_type in ['activity_start', 'activity_end']:
                # Activity points belong to activity entries
                group_key = f"activity_{entry_key}"
                group_type = 'activity'
            else:
                # Visits are standalone
                group_key = f"visit_{entry_key}_{point['lat']}_{point['lon']}"
                group_type = 'visit'
            
            if group_key not in entries:
                entries[group_key] = {
                    'type': group_type,
                    'points': []
                }
            
            entries[group_key]['points'].append(point)
        
        # Sort points within each group by time
        for entry_info in entries.values():
            if entry_info['type'] == 'timelinePath':
                # Sort timeline points by their actual calculated time
                entry_info['points'].sort(key=lambda x: x.get('actual_time', ''))
            else:
                # Sort other points by their sort_time
                entry_info['points'].sort(key=lambda x: x.get('sort_time', ''))
        
        return list(entries.values())
    
    def sort_all_points_chronologically(self, points):
        """Sort ALL points in chronological order"""
        all_points = []
        
        for point in points:
            if point.get('is_timeline', False):
                sort_time = point.get('actual_time', point.get('entry_start_time', ''))
            else:
                sort_time = point.get('entry_start_time', point.get('start_time', ''))
            
            point['sort_time'] = sort_time
            all_points.append(point)
        
        all_points.sort(key=lambda x: x.get('sort_time', ''))
        return all_points
    
    def add_clean_markers(self, map_obj, all_points, colors):
        """Add clean markers without clutter"""
        visit_counter = 1
        
        for i, point in enumerate(all_points):
            point_type = point['type']
            color = colors.get(point_type, 'gray')
            
            if point_type == 'visit':
                # Large numbered markers for visits
                popup_content = f"""
                <b>Visit #{visit_counter}</b><br>
                <b>Location:</b> {point.get('semantic_type', 'Unknown')}<br>
                <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                <b>Time:</b> {point.get('start_time', '')[:16]}<br>
                """
                
                folium.Marker(
                    location=[point['lat'], point['lon']],
                    popup=folium.Popup(popup_content, max_width=300),
                    icon=folium.Icon(color=color, icon='info-sign'),
                    tooltip=f"Visit #{visit_counter}"
                ).add_to(map_obj)
                
                visit_counter += 1
                
            elif point_type in ['activity_start', 'activity_end']:
                # Medium markers for activities
                popup_content = f"""
                <b>{point_type.replace('_', ' ').title()}</b><br>
                <b>Activity:</b> {point.get('activity_type', 'Unknown')}<br>
                <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                """
                
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=6,
                    popup=popup_content,
                    color=color,
                    weight=2,
                    fillColor=color,
                    fillOpacity=0.8
                ).add_to(map_obj)
                
            else:  # timeline_point
                # Small markers for route points
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=3,
                    popup=f"Route point: {point.get('mode', 'unknown')}",
                    color='#FF9800',
                    weight=1,
                    fillColor='#FF9800',
                    fillOpacity=0.6
                ).add_to(map_obj)
    
    def sort_all_points_chronologically(self, points):
        """Sort ALL points in chronological order"""
        all_points = []
        
        for point in points:
            if point.get('is_timeline', False):
                sort_time = point.get('actual_time', point.get('entry_start_time', ''))
            else:
                sort_time = point.get('entry_start_time', point.get('start_time', ''))
            
            point['sort_time'] = sort_time
            all_points.append(point)
        
        # Sort by timestamp
        all_points.sort(key=lambda x: x.get('sort_time', ''))
        return all_points
    
    def add_clean_markers(self, map_obj, all_points, colors):
        """Add clean markers without clutter"""
        visit_counter = 1
        
        for i, point in enumerate(all_points):
            point_type = point['type']
            color = colors.get(point_type, 'gray')
            
            if point_type == 'visit':
                # Large numbered markers for visits
                popup_content = f"""
                <b>Visit #{visit_counter}</b><br>
                <b>Location:</b> {point.get('semantic_type', 'Unknown')}<br>
                <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                <b>Time:</b> {point.get('start_time', '')[:16]}<br>
                """
                
                folium.Marker(
                    location=[point['lat'], point['lon']],
                    popup=folium.Popup(popup_content, max_width=300),
                    icon=folium.Icon(color=color, icon='info-sign'),
                    tooltip=f"Visit #{visit_counter}"
                ).add_to(map_obj)
                
                visit_counter += 1
                
            elif point_type in ['activity_start', 'activity_end']:
                # Medium markers for activities
                popup_content = f"""
                <b>{point_type.replace('_', ' ').title()}</b><br>
                <b>Activity:</b> {point.get('activity_type', 'Unknown')}<br>
                <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                """
                
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=6,
                    popup=popup_content,
                    color=color,
                    weight=2,
                    fillColor=color,
                    fillOpacity=0.8
                ).add_to(map_obj)
                
            else:  # timeline_point
                # Small markers for route points
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=3,
                    popup=f"Route point: {point.get('mode', 'unknown')}",
                    color='#FF9800',
                    weight=1,
                    fillColor='#FF9800',
                    fillOpacity=0.6
                ).add_to(map_obj)
    
    def sort_all_points_chronologically(self, points):
        """Sort ALL points (discrete and timeline) in true chronological order"""
        all_points = []
        
        for point in points:
            # Add timestamp for sorting
            if point.get('is_timeline', False):
                # Timeline points have calculated actual_time
                sort_time = point.get('actual_time', point.get('entry_start_time', ''))
            else:
                # Discrete points use their entry start time
                sort_time = point.get('entry_start_time', point.get('start_time', ''))
            
            point['sort_time'] = sort_time
            all_points.append(point)
        
        # Sort by timestamp
        all_points.sort(key=lambda x: x.get('sort_time', ''))
        
        return all_points
    
    def add_all_markers(self, map_obj, all_points, colors):
        """Add markers for all points with appropriate sizing and numbering"""
        visit_counter = 1
        
        for i, point in enumerate(all_points):
            point_type = point['type']
            color = colors.get(point_type, 'gray')
            
            if point_type == 'visit':
                # Large numbered markers for visits
                popup_content = f"""
                <b>Visit #{visit_counter}</b><br>
                <b>Location:</b> {point.get('semantic_type', 'Unknown')}<br>
                <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                <b>Time:</b> {point.get('start_time', '')[:16]}<br>
                <b>Probability:</b> {point.get('probability', 'N/A')}<br>
                """
                
                folium.Marker(
                    location=[point['lat'], point['lon']],
                    popup=folium.Popup(popup_content, max_width=300),
                    icon=folium.Icon(color=color, icon='info-sign'),
                    tooltip=f"Visit #{visit_counter}"
                ).add_to(map_obj)
                
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=10,
                    popup=f"Visit #{visit_counter}",
                    color='white',
                    weight=2,
                    fillColor=color,
                    fillOpacity=0.9
                ).add_to(map_obj)
                
                visit_counter += 1
                
            elif point_type in ['activity_start', 'activity_end']:
                # Medium markers for activities
                popup_content = f"""
                <b>{point_type.replace('_', ' ').title()}</b><br>
                <b>Activity:</b> {point.get('activity_type', 'Unknown')}<br>
                <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                <b>Time:</b> {point.get('start_time', point.get('end_time', ''))[:16]}<br>
                """
                
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=7,
                    popup=popup_content,
                    color='white',
                    weight=2,
                    fillColor=color,
                    fillOpacity=0.8
                ).add_to(map_obj)
                
            else:  # timeline_point
                # Small markers for timeline points - like the orange dots in the third-party tool
                popup_content = f"""
                <b>Route Point #{i+1}</b><br>
                <b>Mode:</b> {point.get('mode', 'unknown')}<br>
                <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                <b>Time:</b> {point.get('actual_time', '')[:16]}<br>
                """
                
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=4,
                    popup=popup_content,
                    color='#FF9800',
                    weight=1,
                    fillColor='#FF9800',
                    fillOpacity=0.7
                ).add_to(map_obj)
    
    def highlight_unusual_segments(self, map_obj, all_points):
        """Highlight segments that represent unusual jumps or gaps"""
        for i in range(len(all_points) - 1):
            current = all_points[i]
            next_point = all_points[i + 1]
            
            # Calculate distance between consecutive points
            try:
                distance = self.calculate_distance(
                    (current['lat'], current['lon']),
                    (next_point['lat'], next_point['lon'])
                )
                
                # If distance is unusually large (>50km), highlight in red like third-party tool
                if distance > 50000:  # 50km
                    folium.PolyLine(
                        locations=[[current['lat'], current['lon']], 
                                 [next_point['lat'], next_point['lon']]],
                        color='red',
                        weight=4,
                        opacity=0.8,
                        popup=f'Large jump: {distance/1000:.1f}km'
                    ).add_to(map_obj)
                    
            except Exception as e:
                print(f"Error calculating distance: {e}")
                continue
    
    def create_unified_path(self, points):
        """Create a single unified path connecting all points chronologically"""
        # Separate discrete points from timeline points
        discrete_points = [p for p in points if not p.get('is_timeline', False)]
        timeline_points = [p for p in points if p.get('is_timeline', False)]
        
        # Sort discrete points by time
        discrete_points.sort(key=lambda x: x.get('entry_start_time', ''))
        
        # Build unified path by inserting timeline points between discrete points
        unified_path = []
        
        for i, discrete_point in enumerate(discrete_points):
            unified_path.append(discrete_point)
            
            # Look for timeline points that should be inserted after this discrete point
            if i < len(discrete_points) - 1:
                next_discrete = discrete_points[i + 1]
                
                # Find timeline points that chronologically belong between these two discrete points
                intermediate_timeline = self.find_intermediate_timeline_points(
                    discrete_point, next_discrete, timeline_points
                )
                
                # If we found intermediate timeline points, add them
                if intermediate_timeline:
                    unified_path.extend(intermediate_timeline)
                else:
                    # If there's a significant gap and no timeline points, we could add an inferred connection
                    # For now, we'll just let the line connect directly
                    pass
        
        return unified_path
    
    def find_intermediate_timeline_points(self, point1, point2, timeline_points):
        """Find timeline points that logically belong between two discrete points"""
        try:
            import pandas as pd
            
            time1 = pd.to_datetime(point1.get('entry_start_time', ''), utc=True)
            time2 = pd.to_datetime(point2.get('entry_start_time', ''), utc=True)
            
            intermediate = []
            
            for tl_point in timeline_points:
                tl_time = pd.to_datetime(tl_point.get('actual_time', ''), utc=True)
                
                # If timeline point falls between the two discrete points
                if time1 <= tl_time <= time2:
                    # Also check if it's geographically reasonable
                    if self.is_geographically_reasonable(point1, tl_point, point2):
                        intermediate.append(tl_point)
            
            # Sort intermediate points by time
            intermediate.sort(key=lambda x: x.get('actual_time', ''))
            return intermediate
            
        except Exception as e:
            print(f"Error finding intermediate points: {e}")
            return []
    
    def is_geographically_reasonable(self, point1, middle_point, point2):
        """Check if a middle point is geographically reasonable between two points"""
        try:
            # Calculate distances
            dist_1_to_middle = self.calculate_distance(
                (point1['lat'], point1['lon']),
                (middle_point['lat'], middle_point['lon'])
            )
            dist_middle_to_2 = self.calculate_distance(
                (middle_point['lat'], middle_point['lon']),
                (point2['lat'], point2['lon'])
            )
            dist_1_to_2 = self.calculate_distance(
                (point1['lat'], point1['lon']),
                (point2['lat'], point2['lon'])
            )
            
            # If the detour is less than 50% extra distance, it's reasonable
            total_detour = dist_1_to_middle + dist_middle_to_2
            if total_detour <= dist_1_to_2 * 1.5:
                return True
            
            return False
            
        except:
            return True  # If we can't calculate, assume it's reasonable
    
    @staticmethod
    def calculate_distance(coords1, coords2):
        """Calculate distance between two coordinate points in meters."""
        from math import radians, cos, sin, asin, sqrt
        
        lat1, lon1 = coords1
        lat2, lon2 = coords2
        
        # Convert to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        r = 6371  # Earth radius in kilometers
        return c * r * 1000  # Convert to meters
    
    def add_activity_highlights(self, map_obj, unified_path):
        """Add special highlighting for activity segments"""
        for i in range(len(unified_path) - 1):
            current = unified_path[i]
            next_point = unified_path[i + 1]
            
            # If current is activity start and next is activity end from same entry
            if (current['type'] == 'activity_start' and 
                next_point['type'] == 'activity_end' and
                current.get('entry_start_time') == next_point.get('entry_start_time')):
                
                # Add thicker highlight for this activity segment
                folium.PolyLine(
                    locations=[[current['lat'], current['lon']], 
                             [next_point['lat'], next_point['lon']]],
                    color='#1976D2',  # Bright blue for activities
                    weight=6,
                    opacity=0.9,
                    popup=f"Activity: {current.get('activity_type', 'Unknown')}"
                ).add_to(map_obj)
    
    def add_significant_markers(self, map_obj, unified_path, colors):
        """Add numbered markers for visits and activities only"""
        counter = 1
        
        for point in unified_path:
            if point['type'] in ['visit', 'activity_start', 'activity_end']:
                color = colors.get(point['type'], 'gray')
                
                # Create popup content
                if point['type'] == 'visit':
                    popup_content = f"""
                    <b>Stop #{counter}: Visit</b><br>
                    <b>Location:</b> {point.get('semantic_type', 'Unknown')}<br>
                    <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                    <b>Time:</b> {point.get('start_time', '')[:16]}<br>
                    <b>Probability:</b> {point.get('probability', 'N/A')}<br>
                    """
                else:
                    popup_content = f"""
                    <b>Stop #{counter}: {point['type'].replace('_', ' ').title()}</b><br>
                    <b>Activity:</b> {point.get('activity_type', 'Unknown')}<br>
                    <b>Coordinates:</b> {point['lat']:.6f}, {point['lon']:.6f}<br>
                    <b>Time:</b> {point.get('start_time', point.get('end_time', ''))[:16]}<br>
                    """
                
                # Add main marker
                folium.Marker(
                    location=[point['lat'], point['lon']],
                    popup=folium.Popup(popup_content, max_width=300),
                    icon=folium.Icon(color=color, icon='info-sign'),
                    tooltip=f"Stop #{counter}"
                ).add_to(map_obj)
                
                # Add numbered circle
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=10,
                    popup=f"Stop #{counter}",
                    color='white',
                    weight=2,
                    fillColor=color,
                    fillOpacity=0.8
                ).add_to(map_obj)
                
                counter += 1
    
    def add_timeline_markers(self, map_obj, unified_path):
        """Add small, subtle markers for timeline points"""
        for point in unified_path:
            if point.get('is_timeline', False):
                folium.CircleMarker(
                    location=[point['lat'], point['lon']],
                    radius=3,
                    popup=f"Route point: {point.get('mode', 'unknown')}",
                    color='#FF9800',
                    weight=1,
                    fillColor='#FF9800',
                    fillOpacity=0.7
                ).add_to(map_obj)
    
    def setup_routes(self):
        """Setup Flask routes for web interface"""
        
        @self.app.route('/')
        def index():
            return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Location Data Map Viewer</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    .container { max-width: 1200px; margin: 0 auto; }
                    .controls { background: #f5f5f5; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
                    .map-container { width: 100%; height: 600px; border: 1px solid #ccc; }
                    button { padding: 10px 20px; margin: 5px; background: #007cba; color: white; border: none; border-radius: 3px; cursor: pointer; }
                    button:hover { background: #005a8b; }
                    input, select { padding: 5px; margin: 5px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Location Data Map Viewer</h1>
                    <div class="controls">
                        <input type="file" id="fileInput" accept=".json" />
                        <button onclick="loadFile()">Load Map Data</button>
                        <button onclick="refreshMap()">Refresh Map</button>
                        <select id="mapType">
                            <option value="all">Show All Points</option>
                            <option value="visits">Visits Only</option>
                            <option value="activities">Activities Only</option>
                            <option value="timeline">Timeline Points Only</option>
                        </select>
                    </div>
                    <div id="mapContainer" class="map-container">
                        <p>Select a JSON file to view location data on the map.</p>
                    </div>
                </div>
                
                <script>
                    function loadFile() {
                        const fileInput = document.getElementById('fileInput');
                        const file = fileInput.files[0];
                        if (!file) {
                            alert('Please select a file first');
                            return;
                        }
                        
                        const formData = new FormData();
                        formData.append('file', file);
                        
                        fetch('/load_data', {
                            method: 'POST',
                            body: formData
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                refreshMap();
                            } else {
                                alert('Error loading file: ' + data.error);
                            }
                        })
                        .catch(error => {
                            alert('Error: ' + error);
                        });
                    }
                    
                    function refreshMap() {
                        const mapType = document.getElementById('mapType').value;
                        fetch('/generate_map?type=' + mapType)
                        .then(response => response.text())
                        .then(html => {
                            document.getElementById('mapContainer').innerHTML = html;
                        })
                        .catch(error => {
                            alert('Error generating map: ' + error);
                        });
                    }
                </script>
            </body>
            </html>
            ''')
        
        @self.app.route('/load_data', methods=['POST'])
        def load_data_route():
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'No file uploaded'})
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file selected'})
            
            # Save temporarily and load
            temp_path = 'temp_map_data.json'
            file.save(temp_path)
            
            success = self.load_data(temp_path)
            
            # Clean up temp file
            try:
                os.remove(temp_path)
            except:
                pass
            
            if success:
                return jsonify({'success': True, 'points': len(self.extract_coordinates())})
            else:
                return jsonify({'success': False, 'error': 'Failed to load data'})
        
        @self.app.route('/generate_map')
        def generate_map_route():
            map_type = request.args.get('type', 'all')
            
            if not self.map_data:
                return '<p>No data loaded. Please load a JSON file first.</p>'
            
            try:
                map_obj = self.create_map()
                if map_obj:
                    return map_obj._repr_html_()
                else:
                    return '<p>No valid coordinates found in the data.</p>'
            except Exception as e:
                return f'<p>Error generating map: {str(e)}</p>'
    
    def run_web_viewer(self, port=5001, debug=False):
        """Run the web-based map viewer"""
        print(f"Starting Location Map Viewer on http://localhost:{port}")
        print("Upload your parsed JSON file to visualize location data on an interactive map")
        
        # Auto-open browser
        Timer(1, lambda: webbrowser.open(f'http://localhost:{port}')).start()
        
        self.app.run(host='0.0.0.0', port=port, debug=debug)
    
    def save_static_map(self, output_file='location_map.html'):
        """Save map as static HTML file"""
        if not self.map_data:
            print("No data loaded. Load data first.")
            return False
        
        try:
            map_obj = self.create_map()
            if map_obj:
                map_obj.save(output_file)
                print(f"Map saved to {output_file}")
                return True
            else:
                print("No valid coordinates to map")
                return False
        except Exception as e:
            print(f"Error saving map: {e}")
            return False

# Integration function for your main app
def launch_map_viewer_from_task(task_id, username, unified_progress):
    """Launch map viewer using data from a completed analysis task"""
    
    if username not in unified_progress or task_id not in unified_progress[username]:
        print("Task not found")
        return False
    
    progress_data = unified_progress[username][task_id]
    
    # Find the parsed data file
    data_file = None
    
    if 'parsed_data' in progress_data:
        # Data is in memory - save temporarily
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(progress_data['parsed_data'], temp_file, indent=2)
        temp_file.close()
        data_file = temp_file.name
    elif progress_data.get('parsed_file'):
        data_file = progress_data['parsed_file']
    
    if not data_file:
        print("No parsed data found for this task")
        return False
    
    # Create and launch map viewer
    viewer = LocationMapViewer()
    if viewer.load_data(data_file):
        print(f"Launching map viewer for task {task_id[:8]}...")
        viewer.run_web_viewer(port=5001)
        return True
    else:
        print("Failed to load data for mapping")
        return False

if __name__ == "__main__":
    # Standalone usage
    viewer = LocationMapViewer()
    viewer.run_web_viewer()
