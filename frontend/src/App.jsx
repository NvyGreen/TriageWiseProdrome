import { BrowserRouter, Routes, Route } from 'react-router-dom'

import AppLayout from './layouts/AppLayout'
import PatientIntake from './pages/PatientIntake'
import TriageQueue from './pages/TriageQueue'
import PatientDetail from './pages/PatientDetail'


function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route element={<AppLayout />}>
                    <Route path='/' element={<PatientIntake />} />
                    <Route path='/queue' element={<TriageQueue />} />
                    <Route path='/intakes/:intakeId' element={<PatientDetail />} />
                </Route>
            </Routes>
        </BrowserRouter>
    )
}

export default App
