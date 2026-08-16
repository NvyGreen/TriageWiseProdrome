import { useEffect, useState } from 'react';
import { Outlet, Link, NavLink } from 'react-router-dom';
import { Activity, User, List, ChartColumn, LogOut, Clock } from 'lucide-react';

import './AppLayout.css';


// NavLink hands its className a render prop, so the active class is derived
// from the current route rather than hardcoded.
const navClass = ({ isActive }) => (isActive ? 'active' : undefined);

const clockFormat = {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true
};


export default function AppLayout() {
    const [now, setNow] = useState(() => new Date());

    // A stale clock is worse than no clock in a triage tool, so it keeps itself
    // current. Half-minute ticks keep the displayed minute honest.
    useEffect(() => {
        const timer = setInterval(() => setNow(new Date()), 30000);

        return () => clearInterval(timer);
    }, []);

    return (
        <div className='app'>
            <aside className='side'>
                <div className='brandrow'>
                    <span className='logo'>
                        <Activity size={18} />
                    </span>
                    <span className='word'>
                        TriageWise
                        <small>Triage System</small>
                    </span>
                </div>

                <div className='brandrule' />

                {/* Reports has no route yet, so it stays a plain Link and never
                    takes the active class. */}
                <nav className='nav'>
                    <NavLink to='/' end className={navClass}>
                        <User size={17} />
                        <span>Patient Intake</span>
                    </NavLink>
                    <NavLink to='/queue' className={navClass}>
                        <List size={17} />
                        <span>Triage Queue</span>
                    </NavLink>
                    <Link to='/'>
                        <ChartColumn size={17} />
                        <span>Reports &amp; Metrics</span>
                    </Link>
                </nav>

                <div className='foot'>
                    <Link to='/'>
                        <LogOut size={16} />
                        <span>Logout</span>
                    </Link>
                </div>
            </aside>

            <div className='main'>
                <header className='topbar'>
                    <div className='title'>
                        <span className='logo'>
                            <Activity size={18} />
                        </span>
                        TriageWiseProdrome — Clinical Triage &amp; Prioritization System
                    </div>

                    <div className='right'>
                        <span className='clock'>
                            <Clock size={15} />
                            {now.toLocaleString('en-US', clockFormat)}
                        </span>
                    </div>
                </header>

                <Outlet />
            </div>
        </div>
    );
}
