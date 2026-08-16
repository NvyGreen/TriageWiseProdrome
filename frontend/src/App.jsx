import { BrowserRouter, Routes, Route } from 'react-router-dom'

import AppLayout from './layouts/AppLayout'
import PatientIntake from './pages/PatientIntake'
import TriageQueue from './pages/TriageQueue'


function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route element={<AppLayout />}>
                    <Route path='/' element={<PatientIntake />} />
                    <Route path='/queue' element={<TriageQueue />} />
                </Route>
            </Routes>
        </BrowserRouter>
    )
}

export default App
